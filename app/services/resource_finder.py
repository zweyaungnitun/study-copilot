"""Videos and articles for a chapter, picked by the model from a live Google Search and checked before use.

The model searches the web (Gemini grounding with Google Search) and proposes YouTube videos and written
tutorials. Model-written URLs can be wrong or stale, so nothing is kept unverified:

* YouTube links go through YouTube's oEmbed endpoint, which only answers for real, embeddable videos and gives
  the true title, channel and thumbnail.
* Other links are fetched with ``web_source.fetch`` (public addresses only, redirects re-checked), and the page's
  own title replaces the model's.

The pages the grounded answer drew on are candidates too, so a slip in a model-written URL doesn't cost a slot.
Offline, or when nothing survives the checks, callers fall back to plain search links.
"""
import asyncio
import html
import json
import logging
import re
from typing import Any, Dict, List, Optional

import httpx

from app.services import web_source
from app.services.llm_client import llm_client
from app.services.study_guide_service import make_resource, valid_url

logger = logging.getLogger("studypilot.resources")

MAX_VIDEOS = 3
MAX_ARTICLES = 3
OEMBED_URL = "https://www.youtube.com/oembed"
CHECK_TIMEOUT_SECONDS = 10.0
FIND_TIMEOUT_SECONDS = 60.0

# Tests swap in an httpx.MockTransport for the oEmbed calls.
_transport: Optional[httpx.AsyncBaseTransport] = None

_YT_ID = re.compile(r"(?:youtube\.com/(?:watch\?(?:[^#]*&)?v=|shorts/|embed/|live/)|youtu\.be/)([A-Za-z0-9_-]{11})")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)


def youtube_id(url: str) -> Optional[str]:
    m = _YT_ID.search(url)
    return m.group(1) if m else None


def _parse(text: str) -> Dict[str, Any]:
    """The JSON object in a grounded answer (search-grounded calls can't use JSON mode, so it may be wrapped in prose)."""
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _picks(data: Dict[str, Any], key: str) -> List[Dict[str, str]]:
    out = []
    for item in data.get(key) or []:
        if isinstance(item, dict) and isinstance(item.get("url"), str) and valid_url(item["url"]):
            out.append({"url": item["url"].strip(), "title": str(item.get("title") or "").strip(),
                        "why": str(item.get("why") or "").strip()[:240]})
    return out


async def check_video(url: str, why: str = "") -> Optional[Dict[str, Any]]:
    """A resource for a real YouTube video, or None."""
    vid = youtube_id(url)
    if not vid:
        return None
    watch = f"https://www.youtube.com/watch?v={vid}"
    try:
        async with httpx.AsyncClient(transport=_transport, timeout=CHECK_TIMEOUT_SECONDS) as client:
            r = await client.get(OEMBED_URL, params={"url": watch, "format": "json"})
        data = r.json() if r.status_code == 200 else None
    except (httpx.HTTPError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("title"):
        return None
    res = make_resource("video", str(data["title"]), watch, "ai")
    res.update(thumbnail=f"https://i.ytimg.com/vi/{vid}/hqdefault.jpg", author=str(data.get("author_name") or "")[:120], note=why)
    return res


async def check_page(url: str, title: str = "", why: str = "") -> Optional[Dict[str, Any]]:
    """A resource for a reachable web page (or the video it redirects to), or None."""
    if youtube_id(url):
        return await check_video(url, why)
    try:
        final, _ctype, body = await asyncio.wait_for(web_source.fetch(url), CHECK_TIMEOUT_SECONDS)
    except (web_source.WebSourceError, asyncio.TimeoutError):
        return None
    if youtube_id(final):
        return await check_video(final, why)
    m = _TITLE.search(body[:200_000])
    page_title = re.sub(r"\s+", " ", html.unescape(m.group(1))).strip() if m else ""
    res = make_resource("article", page_title or title or web_source.host_of(final), final, "ai")
    res.update(author=web_source.host_of(final), note=why)
    return res


class ResourceFinder:
    @staticmethod
    def prompt(chapter_title: str, subject_name: str, objectives: List[str]) -> str:
        goals = "\n".join(f"- {o}" for o in objectives[:5])
        return f"""Use Google Search to find the best free resources for learning this chapter.
Chapter: {chapter_title}
Subject: {subject_name}
{"The learner should be able to:" + chr(10) + goals if goals else ""}

Find:
- {MAX_VIDEOS + 1} YouTube videos that teach exactly this topic: clear explanations from well-known educators or channels,
  preferably under 30 minutes. Link to individual videos (youtube.com/watch?v=...), not channels or playlists.
- {MAX_ARTICLES + 1} written tutorials or blog posts: official documentation, university pages or well-known
  technical blogs. Free to read, no forums, no paywalls.

Only use URLs that appeared in your search results; never guess a URL. Return only JSON:
{{"videos": [{{"url": string, "title": string, "why": string}}], "articles": [{{"url": string, "title": string, "why": string}}]}}
"why" is one short sentence on why it suits this chapter."""

    @classmethod
    async def find(cls, chapter_title: str, subject_name: str = "", objectives: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Verified videos first, then articles. Empty when offline or nothing checks out."""
        try:
            return await asyncio.wait_for(cls._find(chapter_title, subject_name, objectives or []), FIND_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            logger.warning("Resource search timed out for %r", chapter_title)
            return []

    @classmethod
    async def _find(cls, chapter_title: str, subject_name: str, objectives: List[str]) -> List[Dict[str, Any]]:
        if not llm_client.is_live:
            return []
        result = await llm_client.generate([{"role": "user", "parts": [{"text": cls.prompt(chapter_title, subject_name, objectives)}]}],
                                           temperature=0.2, max_tokens=4096, search=True)
        if not result:
            return []
        data = _parse(result.text)
        videos, articles = _picks(data, "videos"), _picks(data, "articles")
        cited = [s for s in result.sources if valid_url(s["uri"])][:8]

        checks = await asyncio.gather(
            *(check_video(v["url"], v["why"]) for v in videos),
            *(check_page(a["url"], a["title"], a["why"]) for a in articles),
            *(check_page(s["uri"], s.get("title", "")) for s in cited),
        )
        found_videos: List[Dict[str, Any]] = []
        found_articles: List[Dict[str, Any]] = []
        seen = set()
        for res in checks:
            if not res or res["url"] in seen:
                continue
            seen.add(res["url"])
            bucket, cap = (found_videos, MAX_VIDEOS) if res["type"] == "video" else (found_articles, MAX_ARTICLES)
            if len(bucket) < cap:
                bucket.append(res)
        logger.info("Resources for %r: %d/%d videos, %d/%d articles verified", chapter_title,
                    len(found_videos), len(videos), len(found_articles), len(articles) + len(cited))
        return found_videos + found_articles
