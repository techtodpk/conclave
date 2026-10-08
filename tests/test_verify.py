import json

from typer.testing import CliRunner

from conclave.cli import app
from conclave.sources import CitedSource
from conclave.verify import (
    CheckedClaim,
    apply_verdicts,
    attach_passages,
    label,
    parse_claims,
    source_ids,
)
from conftest import PAGE_A, PAGE_B, answer, stage_of

runner = CliRunner()
SONNET = "anthropic/claude-sonnet-5.5"
GPT = "openai/gpt-6.1-sol"


def _init(workspace):
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0, result.output


def _ask(workspace, *args):
    return runner.invoke(app, ["ask", *args, "--config", str(workspace.config)])


def _run_dir(workspace, topic="sky"):
    (run,) = sorted((workspace.store / "topics" / topic / "runs").glob("*"))
    return run


def _full(workspace, openrouter, *extra):
    _init(workspace)
    workspace.set_key()
    result = _ask(workspace, "Why is the sky blue?", "--full", "-t", "sky", *extra)
    assert result.exit_code == 0, result.output
    return result


# --- a whole run --------------------------------------------------------------------


def test_members_may_search_and_other_stages_may_not(workspace, openrouter):
    _full(workspace, openrouter)

    for body in openrouter.chat_requests:
        if stage_of(body) == "research":
            (tool,) = body["tools"]
            assert tool["type"] == "openrouter:web_search"
            assert tool["parameters"]["engine"] == "exa"
            assert tool["parameters"]["max_uses"] == 3
            assert "You can search the web" in body["messages"][0]["content"]
        else:
            assert "tools" not in body, stage_of(body)


def test_full_run_checks_claims_against_fetched_pages(workspace, openrouter):
    result = _full(workspace, openrouter)
    run = _run_dir(workspace)

    assert openrouter.asked_in("extract") == [SONNET]
    assert openrouter.asked_in("check") == [SONNET]
    assert PAGE_A in openrouter.fetched and PAGE_B in openrouter.fetched

    check = next(b for b in openrouter.chat_requests if stage_of(b) == "check")
    prompt = check["messages"][1]["content"]
    assert "scatter short blue wavelengths" in prompt  # from the fetched page
    assert "(fetched page)" in prompt
    assert "(search excerpt only)" in prompt  # page B is a 404, so its excerpt is used
    assert "var x = 1" not in prompt  # scripts are not page text

    verification = json.loads((run / "verification.json").read_text(encoding="utf-8"))
    first, second, third = verification["claims"]
    assert (first["verdict"], first["label"], first["source"]) == ("supported", "verified", PAGE_A)
    assert (second["verdict"], second["label"]) == ("not found", "single model")
    assert (third["verdict"], third["label"]) == ("no source", "agreed but unchecked")
    assert "Supported: 1." in (run / "verification.md").read_text(encoding="utf-8")

    assert "Evidence: 4 web searches, 2 pages cited, 1 fetched for checking." in result.output
    assert "Key claims: 1 of 3 verified, 0 contradicted" in result.output
    assert "2 searches, 2 cited" in result.output  # Sonnet's research line


def test_chairman_is_given_the_checked_labels(workspace, openrouter):
    _full(workspace, openrouter)

    synthesis = next(b for b in openrouter.chat_requests if stage_of(b) == "synthesis")
    text = synthesis["messages"][1]["content"]
    assert "## Claim checks" in text
    assert "[verified] (responses A, B, C; supported by " + PAGE_A in text
    assert "### Review by the author of Response A" in text


def test_final_page_lists_sources_and_says_what_was_checked(workspace, openrouter):
    _full(workspace, openrouter)
    final = (_run_dir(workspace) / "final.md").read_text(encoding="utf-8")

    assert "Members searched the web 4 times and cited 2 pages." in final
    assert "3 key claims were checked against them: 1 verified, 0 contradicted" in final
    assert "## Sources" in final
    assert f"- S1: [Why the sky is blue]({PAGE_A}), cited by A, B, C" in final
    assert "Nothing here was checked" not in final


def test_sources_are_logged_in_the_run_and_the_topic(workspace, openrouter):
    _full(workspace, openrouter)
    run = _run_dir(workspace)

    cited = json.loads((run / "sources.json").read_text(encoding="utf-8"))
    assert [s["url"] for s in cited] == [PAGE_A, PAGE_B]
    assert cited[0]["fetched"] is True
    assert cited[1]["fetch_error"] == "HTTP 404"
    assert cited[0]["verdicts"] == ["claim 1 supported"]

    log = (workspace.store / "topics" / "sky" / "sources.md").read_text(encoding="utf-8")
    assert f"[Why the sky is blue]({PAGE_A})" in log
    assert "| no (HTTP 404) | claim 2 not found |" in log

    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    assert meta["evidence"] == {
        "searches": 4,
        "distinct_sources": 2,
        "pages_fetched": 1,
        "claims_checked": 3,
        "verified": 1,
        "contradicted": 0,
        "share_verified": 0.33,
    }
    sonnet = next(c for c in meta["calls"] if c["stage"] == "research" and c["model"] == SONNET)
    assert (sonnet["searches"], sonnet["sources_cited"]) == (2, 2)


def test_verified_claim_can_enter_memory_but_an_unbacked_verified_label_cannot(
    workspace, openrouter
):
    patch = {
        "add": [
            {
                "text": "Air scatters blue sunlight more, which is Rayleigh scattering.",
                "label": "verified",
            },
            {"text": "The moon is made of rock and dust.", "label": "verified"},
        ]
    }
    openrouter.reply(SONNET, answer("```json\n" + json.dumps(patch) + "\n```"), stage="memory")

    _full(workspace, openrouter)

    memory = json.loads(
        (workspace.store / "topics" / "sky" / "memory.json").read_text(encoding="utf-8")
    )
    labels = {c["text"]: c["label"] for c in memory["claims"]}
    assert labels["Air scatters blue sunlight more, which is Rayleigh scattering."] == "verified"
    assert labels["The moon is made of rock and dust."] == "agreed but unchecked"


def test_no_search_runs_from_training_data_alone(workspace, openrouter):
    result = _full(workspace, openrouter, "--no-search")

    assert all("tools" not in body for body in openrouter.chat_requests)
    assert openrouter.asked_in("extract") == []
    assert openrouter.fetched == []
    final = (_run_dir(workspace) / "final.md").read_text(encoding="utf-8")
    assert "Nothing here was checked against live sources" in final
    assert "Evidence:" not in result.output


def test_search_can_be_turned_off_in_the_config(workspace, openrouter):
    _init(workspace)
    text = workspace.config.read_text(encoding="utf-8")
    workspace.config.write_text(text.replace("enabled = true", "enabled = false"), "utf-8")
    workspace.set_key()

    assert _ask(workspace, "Q?", "--full").exit_code == 0
    assert all("tools" not in body for body in openrouter.chat_requests)


def test_quick_runs_do_not_search(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    assert _ask(workspace, "Q?").exit_code == 0
    (body,) = openrouter.chat_requests
    assert "tools" not in body
    assert "You have no web access" in body["messages"][0]["content"]


def test_no_citations_means_no_checking(workspace, openrouter):
    for model in (SONNET, GPT, "google/gemini-3.8-flash"):
        openrouter.reply(model, answer("## Answer\n\nNo links."), stage="research")

    result = _full(workspace, openrouter)

    assert openrouter.asked_in("extract") == []
    assert "No member cited a web page" in result.output


def test_unreadable_claim_list_skips_checking_but_keeps_the_page(workspace, openrouter):
    openrouter.reply(SONNET, answer("I could not decide."), stage="extract")

    result = _full(workspace, openrouter)

    assert openrouter.asked_in("check") == []
    assert "list of key claims was unreadable" in result.output
    assert (_run_dir(workspace) / "final.md").exists()
    assert not (_run_dir(workspace) / "verification.md").exists()


def test_checker_can_be_a_different_model(workspace, openrouter):
    _init(workspace)
    text = workspace.config.read_text(encoding="utf-8")
    start = text.index("[profiles.balanced]")
    section_end = text.index("[profiles.", start + 5)
    section = text[start:section_end]
    line = next(x for x in section.splitlines() if x.startswith("checker"))
    new = section.replace(line, 'checker = { model = "openai/gpt-6.1-sol", route = "api" }')
    workspace.config.write_text(text[:start] + new + text[section_end:], "utf-8")
    workspace.set_key()

    assert _ask(workspace, "Q?", "--full").exit_code == 0
    assert openrouter.asked_in("extract") == [GPT]
    assert openrouter.asked_in("check") == [GPT]


# --- the rules, one at a time ----------------------------------------------------------


def _ids(*urls):
    return source_ids([CitedSource(url=u, text="", excerpt="") for u in urls])


def test_claim_list_drops_unknown_letters_and_sources_and_respects_the_limit():
    ids = _ids("https://a.example/1")
    reply = json.dumps(
        {
            "claims": [
                {"text": "One.", "responses": ["A", "Z"], "sources": ["S1", "S9"]},
                {"text": "Only from Z.", "responses": ["Z"], "sources": ["S1"]},
                {"text": "Two.", "responses": ["b"], "sources": [], "disagreement": True},
                {"text": "Three.", "responses": ["A"], "sources": []},
            ]
        }
    )

    claims = parse_claims(reply, ["A", "B"], ids, limit=2)

    assert [(c.text, c.responses, c.sources) for c in claims] == [
        ("One.", ["A"], ["S1"]),
        ("Two.", ["B"], []),
    ]
    assert [c.number for c in claims] == [1, 2]
    assert claims[1].disagreement is True
    assert parse_claims("no json here", ["A"], ids, 5) is None


def _claim_with_passage(text="X is 5.", passage="The manual says X is 5 in every release."):
    claim = CheckedClaim(1, text, ["A", "B"], ["S1"], False)
    claim.passages["S1"] = ("fetched page", passage)
    return claim


def test_verdict_needs_its_quote_to_be_in_the_passage():
    real = _claim_with_passage()
    invented = _claim_with_passage()
    reply = '{"verdicts": [{"claim": 1, "verdict": "supported", "source": "S1", "quote": "%s"}]}'

    assert apply_verdicts(reply % "the manual says X is 5 in every release", [real])
    assert apply_verdicts(reply % "X has been 5 since version two", [invented])

    assert (real.verdict, real.source) == ("supported", "S1")
    assert invented.verdict == "not found"
    assert "quote is not in the source" in invented.note


def test_skipped_claims_are_not_found_and_a_bad_reply_changes_nothing():
    claim = _claim_with_passage()
    assert apply_verdicts('{"verdicts": []}', [claim])
    assert claim.verdict == "not found"

    other = _claim_with_passage()
    assert not apply_verdicts("sorry", [other])
    assert other.verdict == "unreachable"


def test_labels_follow_the_evidence():
    ids = _ids("https://a.example/1", "https://www.a.example/2", "https://b.example/3")

    def make(verdict="not found", responses=("A", "B"), sources=("S1", "S3"), disagree=False):
        claim = CheckedClaim(1, "c", list(responses), list(sources), disagree)
        claim.verdict = verdict
        return label(claim, ids)

    assert make("supported") == "verified"
    assert make("supported", disagree=True) == "verified"
    assert make("contradicted") == "disputed"
    assert make(disagree=True) == "disputed"
    assert make() == "agreed but unchecked"
    assert make(sources=("S1", "S2")) == "single source"  # two pages, one website
    assert make(responses=("A",)) == "single model"
    assert make(sources=()) == "agreed but unchecked"


def test_contradicted_claim_is_disputed_on_the_page(workspace, openrouter):
    reply = {
        "verdicts": [
            {
                "claim": 1,
                "verdict": "contradicted",
                "source": "S1",
                "quote": "scatter short blue wavelengths of sunlight more than long red ones",
            }
        ]
    }
    openrouter.reply(SONNET, answer(json.dumps(reply)), stage="check")

    result = _full(workspace, openrouter)

    data = json.loads((_run_dir(workspace) / "verification.json").read_text(encoding="utf-8"))
    assert data["claims"][0]["label"] == "disputed"
    assert "1 contradicted" in result.output


def test_passages_prefer_the_fetched_page_then_the_excerpt():
    fetched = CitedSource(url="https://a.example", fetched=True, text="Page text about X.")
    excerpt = CitedSource(url="https://b.example", excerpt="Excerpt about X.")
    nothing = CitedSource(url="https://c.example", fetch_error="HTTP 403")
    ids = source_ids([fetched, excerpt, nothing])
    claim = CheckedClaim(1, "X", ["A"], ["S1", "S2", "S3"], False)

    attach_passages([claim], ids, per_claim=3)

    assert claim.passages == {
        "S1": ("fetched page", "Page text about X."),
        "S2": ("search excerpt only", "Excerpt about X."),
    }
