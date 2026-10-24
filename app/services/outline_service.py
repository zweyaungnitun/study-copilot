"""Build a material's outline (section tree) and split its text into per-section segments.

Strategies, in order: PDF bookmarks -> headings detected from font sizes -> Markdown headings (text,
notebooks, OCR output) -> LLM segmentation from sampled page openings -> fixed page windows.
"""
import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings
from app.services.extraction import Extracted, Page

logger = logging.getLogger("studypilot.outline")

MD_HEADING = re.compile(r"^\s{0,3}(#{1,4})\s+(.+?)\s*#*\s*$")
PAGE_WINDOW = 10


@dataclass
class Section:
    title: str
    level: int
    page_start: int
    page_end: int = 0
    index: int = 0
    parent: Optional[int] = None
    word_count: int = 0
    text_sample: str = ""
    summary: str = ""
    key_concepts: List[str] = field(default_factory=list)


@dataclass
class Segment:
    section: int  # index into the sections list
    page: int
    text: str


@dataclass
class Outline:
    source: str  # bookmarks, headings, markdown, llm, pages
    sections: List[Section]
    segments: List[Segment]


# ---------------------------------------------------------------------------- heading detection
def _running_lines(pages: List[Page]) -> set:
    """Lines repeated at the top/bottom edge of many pages (running headers/footers, page furniture).

    Only the first and last two lines of a page are candidates, so repeated body text is never removed.
    """
    counts: Counter = Counter()
    for p in pages:
        edge = p.lines[:2] + p.lines[-2:] if len(p.lines) > 4 else p.lines
        counts.update({l.text.strip().lower() for l in edge if l.text.strip()})
    limit = max(3, int(len(pages) * 0.3))
    return {t for t, c in counts.items() if c >= limit}


def detect_font_headings(pages: List[Page]) -> Dict[Tuple[int, int], Tuple[int, str]]:
    """(page, line index) -> (level, title) for lines set noticeably larger than body text."""
    sizes = Counter()
    for p in pages:
        for l in p.lines:
            if l.size:
                sizes[round(l.size, 1)] += len(l.text)
    if not sizes:
        return {}
    body = sizes.most_common(1)[0][0]
    running = _running_lines(pages)
    cands: Dict[Tuple[int, int], Tuple[float, str]] = {}
    for p in pages:
        page_cands = []
        for i, l in enumerate(p.lines):
            t = l.text.strip()
            if (l.size >= body * 1.15 and 2 < len(t) <= 120 and re.search(r"[A-Za-z]", t)
                    and t.lower() not in running and not re.fullmatch(r"[\d\W]+", t)):
                page_cands.append((i, l.size, t))
        if len(page_cands) <= 6:  # a page full of "headings" is a title page or a figure
            for i, size, t in page_cands:
                cands[(p.number, i)] = (round(size, 1), t)
    distinct = sorted({s for s, _ in cands.values()}, reverse=True)[:3]
    if len(cands) < 2:
        return {}
    level_of = {s: n + 1 for n, s in enumerate(distinct)}
    return {k: (level_of[s], t) for k, (s, t) in cands.items() if s in level_of}


def detect_markdown_headings(pages: List[Page]) -> Dict[Tuple[int, int], Tuple[int, str]]:
    out = {}
    in_code = False
    for p in pages:
        for i, l in enumerate(p.lines):
            if l.text.strip().startswith("```"):
                in_code = not in_code
                continue
            m = None if in_code else MD_HEADING.match(l.text)
            if m and m.group(2).strip():
                out[(p.number, i)] = (len(m.group(1)), m.group(2).strip()[:300])
    return out


# ---------------------------------------------------------------------------- outline assembly
def _from_headings(pages: List[Page], heads: Dict[Tuple[int, int], Tuple[int, str]], source: str,
                   default_title: str) -> Outline:
    sections: List[Section] = []
    segments: List[Segment] = []
    cur: Optional[int] = None
    for p in pages:
        buf: List[str] = []
        for i, l in enumerate(p.lines):
            if (p.number, i) in heads:
                if buf and cur is not None:
                    segments.append(Segment(cur, p.number, "\n".join(buf)))
                elif buf:  # text before the first heading
                    sections.append(Section(default_title, 1, p.number))
                    cur = len(sections) - 1
                    segments.append(Segment(cur, p.number, "\n".join(buf)))
                buf = []
                level, title = heads[(p.number, i)]
                sections.append(Section(title, level, p.number))
                cur = len(sections) - 1
            else:
                buf.append(l.text)
        if buf:
            if cur is None:
                sections.append(Section(default_title, 1, p.number))
                cur = len(sections) - 1
            segments.append(Segment(cur, p.number, "\n".join(buf)))
    return Outline(source, sections, segments)


def _from_page_starts(pages: List[Page], starts: List[Tuple[str, int, int]], source: str) -> Outline:
    """Sections that begin at page boundaries (bookmarks, LLM segmentation, page windows)."""
    starts = sorted(starts, key=lambda s: (s[2], s[1]))
    sections = [Section(t, lvl, pg) for t, lvl, pg in starts]
    if not sections or sections[0].page_start > 1:
        sections.insert(0, Section("Front matter", 1, 1))
    segments = []
    j = 0
    for p in pages:
        # The deepest section starting on or before this page owns it.
        while j + 1 < len(sections) and sections[j + 1].page_start <= p.number:
            j += 1
        if p.text.strip():
            segments.append(Segment(j, p.number, p.text))
    return Outline(source, sections, segments)


def _windows(pages: List[Page], filename: str) -> Outline:
    if len(pages) <= PAGE_WINDOW:
        return _from_page_starts(pages, [(filename, 1, 1)], "pages")
    starts = [(f"Pages {i}-{min(i + PAGE_WINDOW - 1, len(pages))}", 1, i) for i in range(1, len(pages) + 1, PAGE_WINDOW)]
    return _from_page_starts(pages, starts, "pages")


def _finalize(outline: Outline, total_pages: int) -> Outline:
    secs = outline.sections
    # Cap the outline size by collapsing the deepest level until it fits.
    while len(secs) > settings.MAX_OUTLINE_SECTIONS and max(s.level for s in secs) > 1:
        deepest = max(s.level for s in secs)
        keep, remap, last_kept = [], {}, 0
        for i, s in enumerate(secs):
            if s.level < deepest or not keep:
                keep.append(s)
                last_kept = len(keep) - 1
            remap[i] = last_kept
        outline.segments = [Segment(remap[g.section], g.page, g.text) for g in outline.segments]
        secs = keep
    for i, s in enumerate(secs):
        s.index = i
        s.parent = next((j for j in range(i - 1, -1, -1) if secs[j].level < s.level), None)
        # Ends where the next section of the same or a higher level begins.
        nxt = next((secs[j].page_start for j in range(i + 1, len(secs)) if secs[j].level <= s.level), total_pages + 1)
        s.page_end = max(s.page_start, nxt - 1 if nxt > s.page_start else s.page_start)
    words: Counter = Counter()
    samples: Dict[int, List[str]] = {}
    for g in outline.segments:
        words[g.section] += len(g.text.split())
        if sum(len(x) for x in samples.get(g.section, [])) < 1500:
            samples.setdefault(g.section, []).append(g.text)
    for s in secs:
        s.word_count = words[s.index]
        s.text_sample = " ".join(samples.get(s.index, []))[:1500]
    outline.sections = secs
    return outline


async def _llm_segments(pages: List[Page]) -> List[Tuple[str, int, int]]:
    from app.services.llm_client import llm_client
    from app.services.rag_service import UNTRUSTED_NOTICE
    if not llm_client.is_live or len(pages) < 3:
        return []
    step = max(1, len(pages) // 150)
    sample = "\n".join(f'<material page="{p.number}">{p.text[:240].replace(chr(10), " ")}</material>'
                       for p in pages[::step] if p.text.strip())
    prompt = f"""These are the opening lines of pages from a study document ({len(pages)} pages).
Identify where its chapters/sections begin.
{UNTRUSTED_NOTICE}
{sample}

Return JSON: {{"sections": [{{"title": string, "level": 1 or 2, "page_start": int}}]}} in page order, 3 to 60 entries."""
    data = await llm_client.generate_json(prompt, model=llm_client.fast_model, fallback={})
    out = []
    for s in (data.get("sections") if isinstance(data, dict) else None) or []:
        try:
            page = int(s.get("page_start"))
            title = str(s.get("title", "")).strip()[:300]
            level = 2 if int(s.get("level", 1)) >= 2 else 1
        except (TypeError, ValueError, AttributeError):
            continue
        if title and 1 <= page <= len(pages):
            out.append((title, level, page))
    return out if len(out) >= 2 else []


def strip_running_lines(pages: List[Page]) -> None:
    """Remove running headers/footers (same line on many pages) from the text itself."""
    if len(pages) < 4:
        return
    running = _running_lines(pages)
    if not running:
        return
    for p in pages:
        if p.ocr:
            continue
        p.lines = [l for l in p.lines if l.text.strip().lower() not in running]
        p.text = "\n".join(l.text for l in p.lines).strip()


async def build_outline(ex: Extracted, filename: str) -> Outline:
    pages = ex.pages
    total = len(pages)
    if ex.kind == "pdf":
        strip_running_lines(pages)
    if len(ex.bookmarks) >= 2:
        outline = _from_page_starts(pages, [(b.title, b.level, b.page) for b in ex.bookmarks], "bookmarks")
    else:
        heads = detect_font_headings(pages) if ex.kind == "pdf" else {}
        md = detect_markdown_headings(pages)
        if len(heads) >= 2:
            outline = _from_headings(pages, heads, "headings", filename)
        elif len(md) >= 2:
            outline = _from_headings(pages, md, "markdown", filename)
        else:
            starts = await _llm_segments(pages) if ex.kind == "pdf" else []
            outline = _from_page_starts(pages, starts, "llm") if starts else _windows(pages, filename)
    return _finalize(outline, total)


# ---------------------------------------------------------------------------- summaries
_STOP = set("the a an and or of to in for on with by is are was were be this that it as at from which these those "
            "can will we you your their its into than then there also such using use used each other more most".split())


def _body_sentences(s: Section) -> List[str]:
    """Sentences of the section text, skipping heading-like lines at the top."""
    lines = [l.strip() for l in s.text_sample.splitlines()]
    while lines and (len(lines[0]) < 80 and not lines[0].endswith((".", "!", "?", ":"))):
        lines.pop(0)
    return [x for x in re.split(r"(?<=[.!?])\s+", " ".join(lines)) if x]


def _fallback_summaries(sections: List[Section]) -> None:
    """Offline: first sentences as the summary; distinctive terms (TF-IDF across sections) as concepts."""
    docs = [[w for w in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", s.text_sample.lower()) if w not in _STOP] for s in sections]
    df: Counter = Counter(w for d in docs for w in set(d))
    n = max(1, len(sections))
    for s, words in zip(sections, docs):
        s.summary = " ".join(_body_sentences(s)[:2])[:400]  # empty for headings with no text of their own
        tf = Counter(words)
        scored = sorted(tf, key=lambda w: -tf[w] * math.log(1 + n / df[w]))
        s.key_concepts = scored[:5]


async def summarize(sections: List[Section], batch: int = 15) -> None:
    """One cheap fast-model call per batch of sections; deterministic fallback offline."""
    from app.services.llm_client import llm_client
    from app.services.rag_service import UNTRUSTED_NOTICE
    _fallback_summaries(sections)
    if not llm_client.is_live:
        return
    todo = [s for s in sections if s.word_count >= 40]
    for i in range(0, len(todo), batch):
        group = todo[i:i + batch]
        body = "\n".join(f'<material id="S{s.index}" title="{s.title[:120]}">{s.text_sample[:1200]}</material>'
                         for s in group)
        prompt = f"""Summarize each section of a study document for a curriculum planner.
{UNTRUSTED_NOTICE}
{body}

Return JSON: {{"S<n>": {{"summary": "1-2 sentences on what it teaches", "key_concepts": ["3-6 short terms"]}}}}"""
        data = await llm_client.generate_json(prompt, model=llm_client.fast_model, max_tokens=4096, fallback={})
        if not isinstance(data, dict):
            continue
        for s in group:
            item = data.get(f"S{s.index}")
            if isinstance(item, dict) and isinstance(item.get("summary"), str) and item["summary"].strip():
                s.summary = item["summary"].strip()[:600]
                concepts = item.get("key_concepts")
                if isinstance(concepts, list):
                    s.key_concepts = [str(c).strip()[:60] for c in concepts if str(c).strip()][:6]


def estimate_summary_tokens(sections: List[Section]) -> int:
    return sum(min(len(s.text_sample), 1200) // 4 + 80 for s in sections if s.word_count >= 40)


def dump(outline: Outline) -> str:
    """Debug helper."""
    return json.dumps([{"i": s.index, "t": s.title, "l": s.level, "p": [s.page_start, s.page_end], "w": s.word_count}
                       for s in outline.sections], indent=1)


def as_dicts(outline: Outline) -> List[Dict[str, Any]]:
    return [{"index": s.index, "title": s.title, "level": s.level, "page_start": s.page_start,
             "page_end": s.page_end, "word_count": s.word_count} for s in outline.sections]
