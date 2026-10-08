import asyncio

import httpx

from conclave.client import Source
from conclave.sources import (
    best_passage,
    collect,
    domain,
    fetch_page,
    found_in,
    html_to_text,
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


def _fetch(handler):
    async def go():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http:
            return await fetch_page(http, "https://a.example/page")

    return asyncio.run(go())


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
