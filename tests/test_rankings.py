"""Public rankings beside the council's own leaderboard (decision 0015).

LMArena rows are trimmed from the real leaderboard dataset published 13 October 2026.
"""

import asyncio
import json
import time

import httpx
from typer.testing import CliRunner

from conclave import rankings
from conclave.cli import app
from conclave.http import new_client
from conclave.rankings import ARTIFICIAL_ANALYSIS, LMARENA, Board, Entry, match

runner = CliRunner()


def _row(name, org, rating, rank, category="overall"):
    return {
        "model_name": name,
        "organization": org,
        "license": "Proprietary",
        "rating": rating,
        "rating_lower": rating - 5,
        "rating_upper": rating + 5,
        "variance": 4.0,
        "vote_count": 5000.0,
        "rank": float(rank),
        "category": category,
        "leaderboard_publish_date": "2026-10-13",
    }


LMARENA_ROWS = [
    _row("claude-opus-5.5-high", "anthropic", 1516.2, 2),
    _row("gemini-3.8-flash-high", "google", 1499.4, 8),
    _row("claude-sonnet-5.5-xhigh", "anthropic", 1468.0, 30),
    _row("claude-sonnet-5.5", "anthropic", 1440.0, 70),
    _row("deepseek-v4.1-flash-max", "deepseek", 1461.0, 39),
    _row("gpt-6.1-sol-max", "openai", 1455.0, 57),
    _row("gpt-6.1-sol-pro-max", "openai", 1490.0, 12),
    _row("claude-sonnet-5", "anthropic", 1430.0, 80),
]

AA_MODELS = {
    "status": 200,
    "data": [
        {
            "name": "Claude Sonnet 5.5",
            "slug": "claude-sonnet-5-5",
            "model_creator": {"name": "Anthropic", "slug": "anthropic"},
            "evaluations": {"artificial_analysis_intelligence_index": 71.4},
        },
        {
            "name": "Gemini 3.8 Flash (Reasoning)",
            "slug": "gemini-3-8-flash-reasoning",
            "model_creator": {"name": "Google", "slug": "google"},
            "evaluations": {"artificial_analysis_intelligence_index": 73.0},
        },
        {"name": "No score", "slug": "x", "model_creator": {"slug": "x"}, "evaluations": {}},
    ],
}


def _board(source, entries):
    return Board(source, "2026-10-13", time.time(), entries)


def _arena():
    return _board(
        "lmarena",
        [
            Entry(r["model_name"], r["organization"], r["rating"], int(r["rank"]))
            for r in LMARENA_ROWS
        ],
    )


# --- matching -----------------------------------------------------------------------------


def test_matching_allows_reasoning_endings_and_takes_the_best_variant():
    board = _arena()

    sonnet = match("anthropic/claude-sonnet-5.5", board)
    assert (sonnet.name, sonnet.value) == ("claude-sonnet-5.5-xhigh", 1468.0)
    assert match("openai/gpt-6.1-sol", board).name == "gpt-6.1-sol-max"  # not "-pro-max"
    assert match("google/gemini-3.8-flash", board).name == "gemini-3.8-flash-high"
    assert match("deepseek/deepseek-v4.1-flash:batch", board).name == "deepseek-v4.1-flash-max"
    assert match("anthropic/claude-sonnet-5", board).name == "claude-sonnet-5"  # not 5.5
    assert match("anthropic/claude-haiku-5.5", board) is None


def test_matching_needs_the_same_company():
    board = _board("lmarena", [Entry("gpt-6.1-sol-max", "someone-else", 1500.0, 1)])
    assert match("openai/gpt-6.1-sol", board) is None


def test_matching_spells_dots_as_dashes_and_maps_company_names():
    aa = _board("artificial_analysis", [Entry("claude-sonnet-5-5", "anthropic", 71.4, 3)])
    grok = _board("lmarena", [Entry("grok-4.6-high", "xai", 1440.0, 98)])

    assert match("anthropic/claude-sonnet-5.5", aa).value == 71.4
    assert match("x-ai/grok-4.6", grok).name == "grok-4.6-high"


def test_names_file_overrides_the_guess():
    board = _arena()
    overrides = {"lmarena": {"openai/gpt-6.1-sol": "gpt-6.1-sol-pro-max"}}

    assert match("openai/gpt-6.1-sol", board, overrides).name == "gpt-6.1-sol-pro-max"
    assert rankings.load_overrides() == {"lmarena": {}, "artificial_analysis": {}}


# --- fetching -----------------------------------------------------------------------------


def _serve(openrouter, aa_status=200):
    asked = {"lmarena": 0, "aa": 0, "aa_keys": []}

    def arena(request):
        asked["lmarena"] += 1
        assert request.url.path == "/filter"
        assert request.url.params["where"] == "\"category\"='overall'"
        offset = int(request.url.params["offset"])
        page = LMARENA_ROWS[offset : offset + 100]
        rows = [{"row_idx": i, "row": r, "truncated_cells": []} for i, r in enumerate(page)]
        return httpx.Response(200, json={"rows": rows, "num_rows_total": len(LMARENA_ROWS)})

    def aa(request):
        asked["aa"] += 1
        asked["aa_keys"].append(request.headers.get("x-api-key"))
        if aa_status != 200:
            return httpx.Response(aa_status, json={"error": "Invalid API key."})
        return httpx.Response(200, json=AA_MODELS)

    openrouter.hosts["datasets-server.huggingface.co"] = arena
    openrouter.hosts["artificialanalysis.ai"] = aa
    return asked


def _fetch(workspace, refresh=False):
    async def go():
        async with new_client() as http:
            return await rankings.fetch_boards(
                http, workspace.store, workspace.config, refresh=refresh
            )

    return asyncio.run(go())


def test_lmarena_is_read_without_a_key_and_cached_for_a_day(workspace, openrouter, monkeypatch):
    monkeypatch.delenv(rankings.AA_KEY_NAME, raising=False)
    asked = _serve(openrouter)

    first = _fetch(workspace)
    again = _fetch(workspace)

    assert [b.source for b in first.boards] == ["lmarena"]
    assert first.missing_key and first.problems == []
    board = first.boards[0]
    assert board.published == "2026-10-13" and len(board.entries) == len(LMARENA_ROWS)
    assert asked["lmarena"] == 1  # the second read came from the cache
    assert again.boards[0].entries[0].name == "claude-opus-5.5-high"
    assert asked["aa"] == 0

    _fetch(workspace, refresh=True)
    assert asked["lmarena"] == 2


def test_artificial_analysis_uses_the_key_from_the_env_file(workspace, openrouter, monkeypatch):
    monkeypatch.delenv(rankings.AA_KEY_NAME, raising=False)
    workspace.config.parent.mkdir(parents=True, exist_ok=True)
    (workspace.config.parent / ".env").write_text(
        f"{rankings.AA_KEY_NAME}=aa-test-key\n", encoding="utf-8"
    )
    asked = _serve(openrouter)

    fetched = _fetch(workspace)

    assert asked["aa_keys"] == ["aa-test-key"]
    aa = next(b for b in fetched.boards if b.source == "artificial_analysis")
    assert [(e.name, e.value, e.rank) for e in aa.entries] == [
        ("gemini-3-8-flash-reasoning", 73.0, 1),
        ("claude-sonnet-5-5", 71.4, 2),
    ]
    assert not fetched.missing_key


def test_a_rejected_key_is_explained_and_the_cached_copy_kept(workspace, openrouter, monkeypatch):
    monkeypatch.setenv(rankings.AA_KEY_NAME, "wrong")
    _serve(openrouter, aa_status=401)

    fetched = _fetch(workspace)

    assert [b.source for b in fetched.boards] == ["lmarena"]
    assert "did not accept the key" in fetched.problems[0]
    assert not fetched.problems[0].endswith("..")

    # An old copy is shown, with its date, when the source cannot be read now.
    old = _board("artificial_analysis", [Entry("claude-sonnet-5-5", "anthropic", 70.0, 1)])
    old.published, old.fetched_at = "2026-10-01", time.time() - 3 * 86400
    rankings._write_cache(workspace.store, old)
    fetched = _fetch(workspace)
    assert any(b.source == "artificial_analysis" for b in fetched.boards)
    assert "showing the copy from 2026-10-01" in fetched.problems[0]


# --- the table and the command -------------------------------------------------------------


def test_table_has_your_models_your_rankings_and_each_sources_best(openrouter):
    from conclave.catalog import ModelInfo

    catalog = {
        model_id: ModelInfo(model_id, model_id, 0.000002, 0.00001, 1_000_000)
        for model_id in [
            "anthropic/claude-sonnet-5.5",
            "anthropic/claude-opus-5.5",
            "google/gemini-3.8-flash",
            "openai/gpt-6.1-sol",
            "anthropic/claude-opus-5.5:batch",
        ]
    }
    rows = rankings.table(
        [_arena()],
        yours=["anthropic/claude-sonnet-5.5"],
        personal={"openai/gpt-6.1-sol": (0.25, 6)},
        catalog=catalog,
        top=2,
    )

    assert [r.model for r in rows] == [
        "anthropic/claude-opus-5.5",  # 1516: one of the source's best two on OpenRouter
        "google/gemini-3.8-flash",  # 1499
        "anthropic/claude-sonnet-5.5",  # 1468: yours
        "openai/gpt-6.1-sol",  # 1455: on your leaderboard
    ]
    gpt = rows[-1]
    assert (gpt.council, gpt.council_rankings, gpt.yours) == (0.25, 6, False)
    assert rows[2].yours and rows[2].price_in == 2.0 and rows[2].price_out == 10.0


def test_rank_command_shows_sources_dates_and_credits(workspace, openrouter, monkeypatch):
    monkeypatch.delenv(rankings.AA_KEY_NAME, raising=False)
    _serve(openrouter)
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0

    result = runner.invoke(app, ["rank", "--config", str(workspace.config), "--top", "3"])

    assert result.exit_code == 0, result.output
    assert "*anthropic/claude-sonnet-5.5" in result.output
    assert "1468 #30" in result.output
    assert LMARENA.credit in result.output and "2026-10-13" in result.output
    assert LMARENA.url in result.output
    assert f"add {rankings.AA_KEY_NAME}" in result.output
    assert ARTIFICIAL_ANALYSIS.name not in result.output.split("Note:")[-1].split("\n", 1)[1]


def test_rankings_page_api_and_saving_the_key(workspace, openrouter, monkeypatch):
    from starlette.testclient import TestClient

    from conclave.web.app import create_app
    from test_web import HEADERS, _setup

    monkeypatch.delenv(rankings.AA_KEY_NAME, raising=False)
    _serve(openrouter)
    with TestClient(create_app(workspace.config, extra_hosts={"testserver"})) as client:
        _setup(client, workspace)
        data = client.get("/api/rankings").json()
        assert data["missing_key"] is True
        assert data["sources"][0]["credit"] == LMARENA.credit
        sonnet = next(r for r in data["rows"] if r["model"] == "anthropic/claude-sonnet-5.5")
        assert sonnet["yours"] and sonnet["cells"]["lmarena"]["name"] == "claude-sonnet-5.5-xhigh"

        saved = client.post("/api/rankings/key", json={"key": "aa-key"}, headers=HEADERS)
        assert saved.status_code == 200
        env = (workspace.config.parent / ".env").read_text(encoding="utf-8")
        assert f"{rankings.AA_KEY_NAME}=aa-key" in env
        assert "OPENROUTER_API_KEY=" in env  # the other key is kept
        data = client.get("/api/rankings?refresh=1").json()
        assert [s["key"] for s in data["sources"]] == ["lmarena", "artificial_analysis"]


def test_cache_file_is_plain_json(workspace, openrouter, monkeypatch):
    monkeypatch.delenv(rankings.AA_KEY_NAME, raising=False)
    _serve(openrouter)
    _fetch(workspace)
    cached = json.loads(
        (workspace.store / ".cache" / "rankings" / "lmarena.json").read_text(encoding="utf-8")
    )
    assert cached["source"] == "lmarena" and cached["entries"][0]["company"] == "anthropic"
