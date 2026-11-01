"""Learning sources from the web: a page, a section of a docs site, a public Google Doc or a GitHub file.

Pages become Markdown (headings kept, navigation and page chrome dropped), so the regular ingestion
pipeline (outline -> sections -> chunks -> embeddings) treats a website like any uploaded document.

Security: the server fetches URLs that users supply. Every request, and every redirect hop, is resolved
first and refused unless all of the host's addresses are public, and the connection is then pinned to
the checked address, so DNS cannot change between the check and the request (no access to localhost,
the private network or cloud metadata). Only http(s) on ports 80/443, text formats, with size and time
limits. Crawling stays on the same site and section and honors robots.txt.
"""
import asyncio
import ipaddress
import re
import socket
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit
from urllib.robotparser import RobotFileParser

import httpx

BOT = "StudyPilotBot"
USER_AGENT = f"Mozilla/5.0 (compatible; {BOT}/1.0; fetches pages a learner added as study material)"
MAX_BYTES = 3_000_000
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 15.0
MAX_CRAWL_PAGES = 30
CRAWL_DELAY_SECONDS = 0.25  # politeness between pages of one site
MIN_TEXT_CHARS = 200        # below this a page is probably rendered by JavaScript
TEXT_TYPES = {"text/html", "application/xhtml+xml", "text/plain", "text/markdown", "text/x-markdown"}
SKIP_EXTS = re.compile(r"\.(png|jpe?g|gif|svg|webp|ico|pdf|zip|gz|tar|mp4|mp3|woff2?|ttf|css|js|json|xml|txt)$", re.I)

# Tests swap in an httpx.MockTransport.
_transport: Optional[httpx.AsyncBaseTransport] = None


class WebSourceError(ValueError):
    """A source that can't be used, with a message the learner can act on."""


@dataclass
class WebPage:
    url: str
    title: str
    markdown: str
    links: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------- URLs
def normalize_url(raw: str) -> str:
    """A clean absolute http(s) URL without fragment, or WebSourceError."""
    raw = (raw or "").strip()
    if not raw:
        raise WebSourceError("Enter a link.")
    if not re.match(r"^[a-z][a-z0-9+.-]*://", raw, re.I):
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise WebSourceError("Only http and https links are supported.")
    if not parts.hostname or "." not in parts.hostname and not _is_ip(parts.hostname):
        raise WebSourceError("That doesn't look like a web address.")
    if parts.username or parts.password:
        raise WebSourceError("Links with a username or password can't be used.")
    try:
        port = parts.port
    except ValueError:
        raise WebSourceError("That link has an invalid port.")
    if port not in (None, 80, 443):
        raise WebSourceError("Only standard web ports (80 and 443) are supported.")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or "/", parts.query, ""))


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host.strip("[]"))
        return True
    except ValueError:
        return False


GDOC = re.compile(r"^https?://docs\.google\.com/document/d/([\w-]+)", re.I)
GITHUB_BLOB = re.compile(r"^https?://github\.com/([^/]+)/([^/]+)/blob/(.+)$", re.I)


def fetchable_url(url: str) -> str:
    """The URL that returns the content: Google Docs export as Markdown, GitHub files as raw text."""
    if m := GDOC.match(url):
        return f"https://docs.google.com/document/d/{m.group(1)}/export?format=md"
    if m := GITHUB_BLOB.match(url):
        return f"https://raw.githubusercontent.com/{m.group(1)}/{m.group(2)}/{m.group(3)}"
    return url


def _canon(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", "", ""))


# ---------------------------------------------------------------------------- safe fetch
async def _resolve(host: str, port: int) -> List[str]:
    """Public addresses of ``host``; WebSourceError if it has none or any address is not public."""
    try:
        infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror:
        raise WebSourceError(f"Couldn't find {host}. Check the link.")
    ips = list(dict.fromkeys(info[4][0] for info in infos))
    for ip in ips:
        addr = ipaddress.ip_address(ip.split("%")[0])
        if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        if not addr.is_global or addr.is_multicast:
            raise WebSourceError("That address isn't on the public internet, so it can't be added.")
    if not ips:
        raise WebSourceError(f"Couldn't find {host}. Check the link.")
    return ips


async def fetch(url: str) -> Tuple[str, str, str]:
    """GET a public URL safely. Returns (final URL, content type, text)."""
    for _ in range(MAX_REDIRECTS + 1):
        parts = urlsplit(url)
        scheme = parts.scheme.lower()
        if scheme not in ("http", "https"):
            raise WebSourceError("The link redirected somewhere that isn't a web page.")
        port = parts.port or (443 if scheme == "https" else 80)
        if port not in (80, 443):
            raise WebSourceError("The link redirected to a non-standard port.")
        host = parts.hostname or ""
        ip = (await _resolve(host, port))[0]
        pinned = urlunsplit((scheme, f"[{ip}]:{port}" if ":" in ip else f"{ip}:{port}", parts.path or "/", parts.query, ""))
        headers = {"Host": parts.netloc, "User-Agent": USER_AGENT,
                   "Accept": "text/html,application/xhtml+xml,text/markdown,text/plain;q=0.9,*/*;q=0.1"}
        try:
            async with httpx.AsyncClient(transport=_transport, timeout=TIMEOUT_SECONDS, follow_redirects=False) as client:
                request = client.build_request("GET", pinned, headers=headers,
                                               extensions={"sni_hostname": host} if scheme == "https" else {})
                response = await client.send(request, stream=True)
                try:
                    if response.status_code in (301, 302, 303, 307, 308) and response.headers.get("location"):
                        url = urljoin(url, response.headers["location"])
                        continue
                    if response.status_code in (401, 403):
                        raise WebSourceError(f"{host} doesn't allow access to this page ({response.status_code}).")
                    if response.status_code >= 400:
                        raise WebSourceError(f"{host} answered {response.status_code} for this page.")
                    ctype = response.headers.get("content-type", "").split(";")[0].strip().lower()
                    if ctype == "application/pdf":
                        raise WebSourceError("This link is a PDF. Download it and upload the file instead.")
                    if ctype and ctype not in TEXT_TYPES:
                        raise WebSourceError(f"This link isn't a web page or text document ({ctype}).")
                    body = bytearray()
                    async for chunk in response.aiter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise WebSourceError("This page is too large (over 3 MB).")
                    text = bytes(body).decode(response.charset_encoding or "utf-8", errors="replace")
                    return url, ctype or "text/html", text
                finally:
                    await response.aclose()
        except httpx.HTTPError as e:
            raise WebSourceError(f"Couldn't reach {host} ({type(e).__name__}). Try again later.")
    raise WebSourceError("The link redirected too many times.")


# ---------------------------------------------------------------------------- HTML -> Markdown
_SKIP = {"script", "style", "noscript", "svg", "nav", "header", "footer", "aside", "form", "button", "iframe",
         "template", "select", "canvas", "dialog"}
_SKIP_ROLES = {"navigation", "banner", "contentinfo", "search", "complementary"}
_BLOCK = {"p", "div", "section", "article", "main", "ul", "ol", "table", "blockquote", "figure", "figcaption",
          "dl", "dt", "dd", "hr", "details", "summary"}


class _ToMarkdown(HTMLParser):
    """Readable Markdown from a page: prefers <main>/<article>, drops chrome, keeps headings, lists, code."""

    def __init__(self, base: str):
        super().__init__(convert_charrefs=True)
        self.base = base
        self.all: List[str] = []
        self.main: List[str] = []
        self.links: List[str] = []
        self.title = ""
        self.h1 = ""
        self._in_title = self._in_h1 = False
        self._heading = False
        self._skip: Optional[Tuple[str, int]] = None   # (tag, nesting) while inside page chrome
        self._main: Optional[Tuple[str, int]] = None
        self._pre = 0

    def _emit(self, s: str) -> None:
        if self._skip:
            return
        self.all.append(s)
        if self._main:
            self.main.append(s)

    def _enter(self, attr: str, tag: str) -> None:
        cur = getattr(self, attr)
        if cur and cur[0] == tag:
            setattr(self, attr, (tag, cur[1] + 1))

    def _leave(self, attr: str, tag: str) -> None:
        cur = getattr(self, attr)
        if cur and cur[0] == tag:
            setattr(self, attr, (tag, cur[1] - 1) if cur[1] > 1 else None)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self.links.append(urljoin(self.base, a["href"]))  # navigation links too: docs sidebars list the pages
        if tag == "title":
            self._in_title = True
            return
        self._enter("_skip", tag)
        self._enter("_main", tag)
        if self._skip:
            return
        if tag in _SKIP or a.get("role") in _SKIP_ROLES or a.get("aria-hidden") == "true" or "hidden" in a:
            self._skip = (tag, 1)
            return
        if self._main is None and (tag in ("main", "article") or a.get("role") == "main"):
            self._main = (tag, 1)
        if tag == "a" and (re.search(r"headerlink|anchor|permalink", a.get("class") or "")
                           or (a.get("href") or "").startswith("#") and self._heading):
            self._skip = (tag, 1)  # heading permalinks ("¶", "#", "🔗")
            return
        if re.fullmatch(r"h[1-6]", tag):
            self._emit("\n\n" + "#" * int(tag[1]) + " ")
            self._in_h1 = tag == "h1" and not self.h1
            self._heading = True
        elif tag == "li":
            self._emit("\n- ")
        elif tag == "br":
            self._emit("\n")
        elif tag == "pre":
            self._pre += 1
            self._emit("\n\n```\n")
        elif tag == "code" and not self._pre and not self._heading:
            self._emit("`")
        elif tag in ("td", "th"):
            self._emit(" | ")
        elif tag == "tr" or tag in _BLOCK:
            self._emit("\n\n" if tag in _BLOCK else "\n")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
            return
        was_skipping = self._skip is not None
        self._leave("_skip", tag)
        if not was_skipping:
            if re.fullmatch(r"h[1-6]", tag):
                self._emit("\n\n")
                self._in_h1 = self._heading = False
            elif tag == "pre":
                self._pre = max(0, self._pre - 1)
                self._emit("\n```\n\n")
            elif tag == "code" and not self._pre and not self._heading:
                self._emit("`")
            elif tag in _BLOCK:
                self._emit("\n\n")
        self._leave("_main", tag)  # balanced even for tags inside skipped chrome

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        if not self._pre:
            data = re.sub(r"\s+", " ", data)
            if self._heading:
                data = data.replace("¶", "")
        if self._in_h1:
            self.h1 += data
        self._emit(data)


def _tidy(md: str) -> str:
    """Trim stray whitespace from the collapsed text, leaving code fences exactly as they were."""
    out, fence = [], False
    for line in md.splitlines():
        if line.strip().startswith("```"):
            fence = not fence
            out.append(line.strip())
        else:
            out.append(line.rstrip() if fence else line.strip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()


def html_to_markdown(html: str, base_url: str) -> WebPage:
    parser = _ToMarkdown(base_url)
    parser.feed(html)
    parser.close()
    main, everything = _tidy("".join(parser.main)), _tidy("".join(parser.all))
    body = main if len(main) >= MIN_TEXT_CHARS or len(main) >= 0.5 * len(everything) else everything
    title = re.sub(r"\s+", " ", parser.h1 or parser.title).strip(" ¶#") or _title_from_url(base_url)
    return WebPage(base_url, title[:200], body, list(dict.fromkeys(parser.links)))


def _title_from_url(url: str) -> str:
    p = urlsplit(url)
    last = [s for s in p.path.split("/") if s]
    return (re.sub(r"\.\w+$", "", last[-1]).replace("-", " ").replace("_", " ").strip().capitalize() if last else p.hostname) or "Untitled"


def text_page(text: str, url: str) -> WebPage:
    m = re.search(r"^#\s+(.+)$", text, re.M)
    return WebPage(url, (m.group(1).strip() if m else _title_from_url(url))[:200], _tidy(text))


def as_section(page: WebPage) -> str:
    """The page as one Markdown document section: its title as '#', its own headings one level down."""
    lines = page.markdown.splitlines()
    first = next((i for i, l in enumerate(lines) if l.strip()), None)
    if first is not None and re.sub(r"^#+\s*", "", lines[first]).strip() == page.title:
        lines = lines[first + 1:]   # the page's own H1 repeats its title
    out, fence = [], False
    for line in lines:
        if line.startswith("```"):
            fence = not fence
        elif not fence and (m := re.match(r"^(#{1,5})\s", line)):
            line = "#" + line
        out.append(line)
    return f"# {page.title}\n\n" + "\n".join(out).strip()


# ---------------------------------------------------------------------------- pages & crawl
async def fetch_page(url: str) -> WebPage:
    target = fetchable_url(url)
    final, ctype, text = await fetch(target)
    if GDOC.match(url) and "accounts.google.com" in (urlsplit(final).hostname or ""):
        raise WebSourceError("This Google Doc isn't public. Set sharing to 'Anyone with the link' and try again.")
    page = html_to_markdown(text, final) if ctype in ("text/html", "application/xhtml+xml") else text_page(text, final)
    page.url = url if target != url else final
    return page


async def _robots(url: str) -> Optional[RobotFileParser]:
    p = urlsplit(url)
    try:
        _, _, text = await fetch(urlunsplit((p.scheme, p.netloc, "/robots.txt", "", "")))
    except WebSourceError:
        return None
    rp = RobotFileParser()
    rp.parse(text.splitlines())
    return rp


def _in_scope(link: str, start: str) -> bool:
    """Same site and inside the start page's section (its directory)."""
    a, b = urlsplit(link), urlsplit(start)
    if a.scheme not in ("http", "https") or a.netloc.lower() != b.netloc.lower() or SKIP_EXTS.search(a.path):
        return False
    prefix = b.path[: b.path.rfind("/") + 1] or "/"
    return a.path.startswith(prefix)


async def collect(url: str, include_linked: bool = False, max_pages: int = 15,
                  on_page: Optional[Callable[[int], None]] = None) -> List[WebPage]:
    """The page at ``url`` and, with ``include_linked``, the pages it links to in the same docs section
    (breadth-first, which follows the order of a docs sidebar), up to ``max_pages``."""
    start = normalize_url(url)
    first = await fetch_page(start)
    if len(first.markdown) < MIN_TEXT_CHARS:
        raise WebSourceError("This page has almost no readable text. It may need JavaScript to load; "
                             "try a docs page, a print/export view, or save it as a PDF and upload that.")
    pages = [first]
    if not include_linked or fetchable_url(start) != start:
        return pages
    limit = max(1, min(int(max_pages), MAX_CRAWL_PAGES))
    robots = await _robots(start)
    seen = {_canon(start), _canon(first.url)}
    queue = list(first.links)
    while queue and len(pages) < limit:
        link = _canon(queue.pop(0))
        if link in seen or not _in_scope(link, start):
            continue
        seen.add(link)
        if robots and not robots.can_fetch(BOT, link):
            continue
        await asyncio.sleep(CRAWL_DELAY_SECONDS)
        try:
            page = await fetch_page(link)
        except WebSourceError:
            continue
        if len(page.markdown) < 40:
            continue
        pages.append(page)
        queue.extend(page.links)
        if on_page:
            on_page(len(pages))
    return reading_order(pages)


def reading_order(pages: List[WebPage]) -> List[WebPage]:
    """Follow the site's own table of contents when one of the fetched pages is it.

    The TOC page is the one whose in-section links cover most of the other fetched pages (ties: the longest
    list, i.e. a real TOC beats previous/next links). It comes first, then pages in its link order; pages it
    doesn't list keep crawl order at the end. With no such page, crawl order stays.
    """
    if len(pages) < 3:
        return pages
    keys = [_canon(p.url) for p in pages]
    start = pages[0].url

    def toc(p: WebPage) -> Dict[str, int]:
        own, order = _canon(p.url), {}
        for link in p.links:
            k = _canon(link)
            if k != own and _in_scope(k, start):
                order.setdefault(k, len(order))
        return order

    tocs = [toc(p) for p in pages]
    covered = [sum(k in t for k in keys) for t in tocs]
    best = max(range(len(pages)), key=lambda i: (covered[i], len(tocs[i])))
    if covered[best] < 0.6 * (len(pages) - 1):
        return pages
    late = len(tocs[best])
    rank = lambda i: -1 if i == best else tocs[best].get(keys[i], late)
    return [pages[i] for i in sorted(range(len(pages)), key=lambda i: (rank(i), i))]


def host_of(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def site_name(pages: List[WebPage]) -> str:
    """A display name for the material: the start page's title and the site."""
    host = host_of(pages[0].url)
    title = pages[0].title
    return (f"{title} · {host}" if host and host not in title.lower() else title)[:255]


def page_index(pages: List[WebPage]) -> List[Dict[str, str]]:
    return [{"title": p.title, "url": p.url} for p in pages]
