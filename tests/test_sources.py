import asyncio
import ipaddress

import httpx
import pytest

import conclave.http
import conclave.sources
from conclave.client import Source
from conclave.sources import (
    CitedSource,
    best_passage,
    block_reason,
    collect,
    domain,
    fetch_all,
    fetch_page,
    found_in,
    html_to_text,
    new_page_client,
    normalise,
    urls_in,
)


def test_links_in_text_lose_trailing_punctuation_and_repeat_once():
    text = "See [docs](https://a.example/x). Also https://b.example/y, and https://a.example/x."

    assert urls_in(text) == ["https://a.example/x", "https://b.example/y"]


def test_one_spelling_per_page():
    assert normalise("HTTPS://Docs.Example.org/a/#part") == "https://docs.example.org/a"
    assert normalise("https://a.example/t/?featured_on=talkpython") == "https://a.example/t"
    assert normalise("https://a.example/p?id=7&utm_source=x") == "https://a.example/p?id=7"
    assert domain("https://www.example.org/a") == "example.org"


def test_collect_merges_annotations_and_written_links_by_page():
    cited = {
        "A": [Source("https://a.example/x", "Page X", "first excerpt")],
        "B": [Source("https://a.example/x/", "", "second excerpt")],
    }
    pages = collect(cited, {"A": "", "C": "As https://a.example/x#top says."})

    (page,) = pages.values()
    assert page.cited_by == ["A", "B", "C"]
    assert page.title == "Page X"
    assert page.excerpt == "first excerpt\n[...]\nsecond excerpt"


def test_html_text_skips_scripts_and_page_furniture():
    title, text = html_to_text(
        "<html><head><title> The  Title </title><style>p {}</style></head><body>"
        "<nav>Menu</nav><p>First &amp; best.</p><script>alert(1)</script><p>Second.</p>"
        "<footer>Copyright</footer></body></html>"
    )

    assert title == "The Title"
    assert text == "First & best.\nSecond."


def test_best_passage_keeps_the_lines_about_the_claim():
    filler = "\n".join(f"Unrelated line number {n} about gardening." for n in range(300))
    page = filler + "\nThe GIL stops threads running Python bytecode in parallel.\n" + filler

    passage = best_passage("Threads cannot run Python bytecode in parallel under the GIL", page)

    assert "The GIL stops threads running Python bytecode in parallel." in passage
    assert len(passage) <= 2600


def test_short_pages_are_kept_whole():
    assert best_passage("anything", "Short page.") == "Short page."


def test_quotes_match_despite_case_spacing_and_punctuation():
    assert found_in("the GIL  stops threads", "As noted, The GIL stops threads, mostly.")
    assert not found_in("the GIL frees threads", "The GIL stops threads.")
    assert not found_in("GIL", "GIL")  # too short to mean anything


def _fetch(handler, url="https://a.example/page"):
    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            return await fetch_page(http, url)

    original = conclave.sources.resolve_host
    conclave.sources.resolve_host = lambda host: [ipaddress.ip_address("8.8.8.8")]
    try:
        return asyncio.run(go())
    finally:
        conclave.sources.resolve_host = original


def test_fetch_reads_html_and_rejects_what_it_cannot_use():
    body = "<p>" + "Readable words. " * 30 + "</p>"

    def respond(status, kind, content):
        return lambda request: httpx.Response(status, headers={"content-type": kind}, text=content)

    html = respond(200, "text/html", body)
    pdf = respond(200, "application/pdf", "%PDF")
    empty = respond(200, "text/html", "<div id=app></div>")
    gone = respond(403, "text/html", "no")

    def broken(request):
        raise httpx.ConnectTimeout("slow")

    text, error = _fetch(html)
    assert text.startswith("Readable words.") and error == ""
    assert _fetch(pdf) == (None, "not a web page (application/pdf)")
    assert _fetch(empty)[1].startswith("almost no readable text")
    assert _fetch(gone) == (None, "HTTP 403")
    assert _fetch(broken) == (None, "ConnectTimeout")


def test_an_unexpected_fetch_error_is_recorded():
    def broken(request):
        raise OverflowError("connect(): port must be 0-65535.")

    assert _fetch(broken) == (None, "connect(): port must be 0-65535.")


def test_a_bad_port_is_recorded_instead_of_raising():
    async def go():
        async with httpx.AsyncClient() as http:
            return await fetch_page(http, "http://example.com:99999/secret")

    text, error = asyncio.run(go())

    assert text is None
    assert error == "only ports 80 and 443 are fetched"


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://127.0.0.1:80/api",
        "https://10.1.2.3/",
        "http://172.16.0.1/x",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data",
        "http://[::1]/",
        "http://[fc00::1]/",
        "http://[fe80::1]/",
        "http://0.0.0.0/",
        "http://localhost/",
        "http://printer.local/",
        "file:///etc/passwd",
        "http://docs.example:8080/",
        "http://docs.example:99999/",
        "http://user:pass@docs.example/",
        "ftp://8.8.8.8/",
    ],
)
def test_internal_and_non_web_urls_are_blocked(url):
    assert block_reason(url) is not None


def test_public_http_and_https_on_standard_ports_are_allowed(monkeypatch):
    monkeypatch.setattr(
        conclave.sources, "resolve_host", lambda host: [ipaddress.ip_address("8.8.8.8")]
    )

    assert block_reason("https://docs.example/a") is None
    assert block_reason("http://docs.example/a") is None
    assert block_reason("https://docs.example:443/a") is None
    assert block_reason("http://8.8.8.8/dns") is None


def test_numeric_host_tricks_are_blocked_when_they_resolve_to_loopback(monkeypatch):
    monkeypatch.setattr(
        conclave.sources, "resolve_host", lambda host: [ipaddress.ip_address("127.0.0.1")]
    )

    assert block_reason("http://2130706433/") == "not a public address"
    assert block_reason("http://127.1/") == "not a public address"
    # Some parsers reject a leading-zero address outright. Either way it is not fetched.
    assert block_reason("http://0177.0.0.1/") is not None


def test_a_hostname_is_blocked_when_any_address_is_private(monkeypatch):
    monkeypatch.setattr(
        conclave.sources,
        "resolve_host",
        lambda host: [ipaddress.ip_address("8.8.8.8"), ipaddress.ip_address("169.254.169.254")],
    )

    assert block_reason("http://metadata.example/latest") == "not a public address"


def test_an_unresolved_host_is_not_fetched(monkeypatch):
    def boom(host):
        raise OSError("no")

    monkeypatch.setattr(conclave.sources, "resolve_host", boom)

    assert block_reason("http://missing.example/") == "could not resolve the host"


def test_redirect_to_a_private_address_is_not_followed(monkeypatch):
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.host == "docs.example":
            return httpx.Response(302, headers={"location": "http://127.0.0.1/secret"})
        return httpx.Response(200, text="secret " * 40)

    monkeypatch.setattr(conclave.http, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(
        conclave.sources, "resolve_host", lambda host: [ipaddress.ip_address("8.8.8.8")]
    )

    async def go():
        async with new_page_client() as http:
            return await fetch_page(http, "http://docs.example/start")

    text, error = asyncio.run(go())

    assert text is None
    assert error == "not a public address"
    assert seen == ["http://docs.example/start"]


def test_redirect_to_another_public_page_is_fetched(monkeypatch):
    seen = []
    body = "Readable words. " * 30

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/start":
            return httpx.Response(302, headers={"location": "https://docs.example/page"})
        return httpx.Response(200, headers={"content-type": "text/html"}, text=f"<p>{body}</p>")

    monkeypatch.setattr(conclave.http, "TRANSPORT", httpx.MockTransport(handler))
    monkeypatch.setattr(
        conclave.sources, "resolve_host", lambda host: [ipaddress.ip_address("8.8.8.8")]
    )

    async def go():
        async with new_page_client() as http:
            return await fetch_page(http, "http://docs.example/start")

    text, error = asyncio.run(go())

    assert error == ""
    assert text.startswith("Readable words.")
    assert seen == ["http://docs.example/start", "https://docs.example/page"]


def test_fetch_all_records_a_blocked_page_and_does_not_raise():
    async def go():
        page = CitedSource("http://169.254.169.254/latest")
        async with httpx.AsyncClient() as http:
            await fetch_all(http, [page])
        return page

    page = asyncio.run(go())

    assert page.fetched is False
    assert page.fetch_error == "not a public address"


def test_quote_may_not_join_text_across_a_gap():
    passage = "The build is supported but\n[...]\nstill optional for now."

    assert found_in("the build is supported", passage)
    assert not found_in("supported but still optional", passage)


def test_neighbouring_windows_are_joined_without_a_gap_marker():
    lines = [f"Filler line {n} about gardening and weather." for n in range(200)]
    lines[90:96] = [
        "The GIL can be disabled in the free-threaded build.",
        "The free-threaded build is officially supported in 3.14.",
        "It remains optional and is not the default build.",
        "Extensions must declare support for the free-threaded build.",
        "Otherwise the GIL is enabled again on import.",
        "A warning is printed when the GIL is enabled again.",
    ]
    passage = best_passage(
        "The free-threaded build is supported, optional, and the GIL is enabled again on import",
        "\n".join(lines),
        limit=600,
    )

    assert "officially supported in 3.14.\nIt remains optional" in passage


def test_passage_windows_are_kept_whole():
    lines = [f"Unrelated filler line {n} about the weather today." for n in range(100)]
    lines[50] = "The GIL may be enabled again on import. " + "A warning is printed then. " * 3
    passage = best_passage("GIL enabled again on import with a warning", "\n".join(lines), 400)

    assert "A warning is printed then. A warning is printed then. A warning" in passage
    assert all(line.rstrip().endswith(".") or line == "[...]" for line in passage.split("\n"))
