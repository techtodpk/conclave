"""Web sources: collecting what members cited, fetching pages, and finding the passages
that bear on a claim.

Pages are fetched on the user's own machine, with no service in between. A page that
cannot be fetched falls back to the excerpt the search returned, and the verdict says so.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urlsplit, urlunsplit

import httpx

from conclave.budget import PASSAGE_CHARS
from conclave.client import Source

FETCH_TIMEOUT_SECONDS = 15.0
FETCH_MAX_BYTES = 3_000_000
FETCH_AT_ONCE = 6
MAX_PAGES = 16
USER_AGENT = "Mozilla/5.0 (compatible; Conclave/0.5; +https://github.com/techtodpk/conclave)"

_URL = re.compile(r"https?://[^\s<>()\[\]\"'`]+")
_TRAILING = ".,;:!?*_"


# Query parameters that only say where a link was shared, not which page it is.
TRACKING = re.compile(r"^(utm_\w+|featured_on|ref|ref_src|fbclid|gclid|mc_cid|mc_eid)$", re.I)


def normalise(url: str) -> str:
    """One spelling per page: lower-case host, no fragment, no trailing slash, no tracking."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return url.strip()
    path = parts.path.rstrip("/") or ""
    query = "&".join(
        pair for pair in parts.query.split("&") if pair and not TRACKING.match(pair.split("=")[0])
    )
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, query, ""))


def domain(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    return host[4:] if host.startswith("www.") else host


def urls_in(text: str) -> list[str]:
    """Links written in a model's text, in order, each once."""
    found: dict[str, None] = {}
    for match in _URL.finditer(text):
        url = match.group(0).rstrip(_TRAILING)
        found.setdefault(url, None)
    return list(found)


@dataclass
class CitedSource:
    """One page cited in a run, by whom, and what Conclave found when it fetched it."""

    url: str
    title: str = ""
    excerpt: str = ""
    cited_by: list[str] = field(default_factory=list)  # response letters
    fetched: bool = False
    fetch_error: str | None = None
    text: str = ""  # the page's readable text, when fetched


def collect(cited: dict[str, list[Source]], written: dict[str, str]) -> dict[str, CitedSource]:
    """Every page a run's members cited, keyed by normalised URL.

    `cited` maps a response letter to the pages its search annotations named; `written`
    maps a letter to its answer text, whose own links are counted too.
    """
    pages: dict[str, CitedSource] = {}

    def add(letter: str, url: str, title: str = "", excerpt: str = "") -> None:
        key = normalise(url)
        page = pages.setdefault(key, CitedSource(url=url))
        if title and not page.title:
            page.title = title
        if excerpt and excerpt not in page.excerpt:
            page.excerpt = f"{page.excerpt}\n[...]\n{excerpt}" if page.excerpt else excerpt
        if letter not in page.cited_by:
            page.cited_by.append(letter)

    for letter, found in cited.items():
        for source in found:
            add(letter, source.url, source.title, source.excerpt)
    for letter, text in written.items():
        for url in urls_in(text):
            add(letter, url)
    return pages


# --- fetching ---------------------------------------------------------------------


class _Text(HTMLParser):
    """Readable text from HTML: skips scripts, styles and page furniture."""

    SKIP = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}
    BLOCK = {
        "p",
        "div",
        "li",
        "br",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "tr",
        "section",
        "article",
        "pre",
        "blockquote",
        "dd",
        "dt",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self.SKIP:
            self.skipping += 1
        elif tag == "title":
            self._in_title = True
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1
        elif tag == "title":
            self._in_title = False
        elif tag in self.BLOCK:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self.title += data
        elif not self.skipping:
            self.parts.append(data)


def html_to_text(html: str) -> tuple[str, str]:
    """(title, text) of an HTML page."""
    parser = _Text()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # noqa: BLE001 - a broken page gives what was read so far
        pass
    lines = (" ".join(line.split()) for line in "".join(parser.parts).splitlines())
    text = "\n".join(line for line in lines if line)
    return " ".join(parser.title.split()), text


async def fetch_page(http: httpx.AsyncClient, url: str) -> tuple[str | None, str]:
    """(text, error). Text is None when the page could not be read."""
    try:
        async with http.stream("GET", url) as response:
            if response.status_code != 200:
                return None, f"HTTP {response.status_code}"
            kind = response.headers.get("content-type", "").lower()
            if kind and "html" not in kind and "text/plain" not in kind:
                return None, f"not a web page ({kind.split(';')[0]})"
            body = b""
            async for chunk in response.aiter_bytes():
                body += chunk
                if len(body) > FETCH_MAX_BYTES:
                    return None, "page too large"
            encoding = response.encoding or "utf-8"
    except httpx.HTTPError as error:
        return None, type(error).__name__
    raw = body.decode(encoding, errors="replace")
    text = html_to_text(raw)[1] if "html" in kind or "<html" in raw[:2000].lower() else raw
    if len(text) < 200:
        return None, "almost no readable text (the page may need JavaScript)"
    return text, ""


async def fetch_all(http: httpx.AsyncClient, pages: list[CitedSource]) -> None:
    """Fetch pages at the same time, a few at once, filling in text or the reason it failed."""
    gate = asyncio.Semaphore(FETCH_AT_ONCE)

    async def one(page: CitedSource) -> None:
        async with gate:
            text, error = await fetch_page(http, page.url)
        page.fetched = text is not None
        page.text = text or ""
        page.fetch_error = error or None

    await asyncio.gather(*(one(page) for page in pages[:MAX_PAGES]))
    for page in pages[MAX_PAGES:]:
        page.fetch_error = "not fetched: too many pages in one run"


def new_page_client() -> httpx.AsyncClient:
    """A client for fetching cited pages. Uses the same test transport as the API client."""
    from conclave import http as http_module

    return httpx.AsyncClient(
        timeout=httpx.Timeout(FETCH_TIMEOUT_SECONDS, connect=8.0),
        follow_redirects=True,
        transport=http_module.TRANSPORT,
        headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain;q=0.9,*/*;q=0.5"},
    )


# --- passages ---------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9][a-z0-9.\-]*[a-z0-9]|[a-z0-9]")
STOPWORDS = frozenset(
    "a an the and or but if of to in on at by for with from as is are was were be been being "
    "it its this that these those than then so such not no can could may might will would "
    "should do does did has have had which who whom what when where why how all any each "
    "more most other some into over under about between through also only very".split()
)


def words(text: str) -> set[str]:
    """Content words, lower-cased, with a plural s dropped, for overlap scores."""
    out = set()
    for word in _WORD.findall(text.lower()):
        if word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        out.add(word)
    return out


def best_passage(claim: str, text: str, limit: int = PASSAGE_CHARS) -> str:
    """The part of a page most likely to confirm or refute a claim, at most `limit` characters.

    Splits the page into windows of a few lines and keeps the windows that share the most
    content words with the claim, in page order.
    """
    if len(text) <= limit:
        return text
    target = words(claim)
    lines = [line for line in text.splitlines() if line.strip()]
    windows: list[tuple[int, str]] = []
    step = 3
    for start in range(0, len(lines), step):
        chunk = "\n".join(lines[start : start + step])
        windows.append((start, chunk))
    scored = sorted(windows, key=lambda w: -len(target & words(w[1])))
    chosen: list[tuple[int, str]] = []
    used = 0
    for start, chunk in scored:
        if not target & words(chunk) and chosen:
            break  # the rest share no words with the claim
        if used + len(chunk) > limit:
            if chosen:
                continue  # keep windows whole: a cut sentence can change what a page says
            chunk = chunk[:limit]
        chosen.append((start, chunk))
        used += len(chunk) + 7
    chosen.sort()
    out = ""
    for index, (start, piece) in enumerate(chosen):
        if index == 0:
            out = piece
        elif start == chosen[index - 1][0] + step:
            out += "\n" + piece  # the next window on the page: no gap to mark
        else:
            out += "\n[...]\n" + piece
    return out


def found_in(quote: str, text: str) -> bool:
    """Whether a quoted phrase appears in a text, ignoring case, spacing and punctuation.

    The quote must come from one stretch of the text: it may not join words from either
    side of a "[...]" gap, which would stitch together sentences the page keeps apart.
    """

    def flat(value: str) -> str:
        return " ".join(re.sub(r"[^\w]+", " ", value.lower()).split())

    needle = flat(quote)
    if len(needle) < 12:
        return False
    return any(needle in flat(part) for part in text.split("[...]"))
