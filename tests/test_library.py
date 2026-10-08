import json
import sqlite3
from contextlib import closing

from typer.testing import CliRunner

from conclave import library
from conclave.cli import app

runner = CliRunner()


def _init(workspace):
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0, result.output


def _run(workspace, *args):
    return runner.invoke(app, [*args, "--config", str(workspace.config)])


def _rankings(store, topic, name, responses, rankings):
    folder = store / "topics" / topic / "runs" / name
    folder.mkdir(parents=True)
    data = {"responses": responses, "reviews": [{"ranking": r} for r in rankings]}
    (folder / "rankings.json").write_text(json.dumps(data), encoding="utf-8")


def test_leaderboard_scales_places_and_counts_firsts(tmp_path):
    _rankings(
        tmp_path,
        "a",
        "r1",
        {"A": "x/one", "B": "y/two", "C": "z/three"},
        [["B", "C"], ["A", "C"], ["A", "B"]],
    )
    _rankings(tmp_path, "b", "r2", {"A": "y/two", "B": "x/one"}, [["A"], ["B"], None])

    table = library.leaderboard(tmp_path)

    assert [(p.model, p.score, p.firsts, p.rankings, p.runs) for p in table] == [
        ("x/one", 0.0, 3, 3, 2),
        ("y/two", 0.333, 2, 3, 2),
        ("z/three", 1.0, 0, 2, 1),
    ]
    only_b = library.leaderboard(tmp_path, "b")
    assert {p.model for p in only_b} == {"x/one", "y/two"}


def test_leaderboard_skips_broken_files(tmp_path):
    folder = tmp_path / "topics" / "a" / "runs" / "bad"
    folder.mkdir(parents=True)
    (folder / "rankings.json").write_text("{nope", encoding="utf-8")

    assert library.leaderboard(tmp_path) == []


def test_full_workflow_through_the_commands(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    assert "No topics yet" in _run(workspace, "topics").output

    _run(workspace, "ask", "Is Unity DOTS ready for production?", "--full", "-t", "unity")
    _run(workspace, "ask", "What is a goroutine?", "-t", "go")
    _run(workspace, "note", "unity", "We ship on low-end Android phones.")

    topics = _run(workspace, "topics").output
    lines = [line.split() for line in topics.splitlines()]
    assert ["go", "1", "0", "0", "0"] == lines[1][:5]
    assert ["unity", "1", "1", "1", "1"] == lines[2][:5]
    assert "(notes)" in topics.splitlines()[2]

    show = _run(workspace, "show", "Unity").output
    assert "C1  A claim. [agreed but unchecked]" in show
    assert "D1  Whether the claim holds everywhere." in show
    assert "We ship on low-end Android phones." in show
    assert "(full)" in show

    found = _run(workspace, "search", "android").output
    assert "topics/unity/notes.md  [notes]" in found
    assert "low-end Android" in found

    scoped = _run(workspace, "search", "goroutine", "--topic", "unity").output
    assert scoped.strip() == "Nothing found."
    assert "question" in _run(workspace, "search", "goroutine").output

    board = _run(workspace, "leaderboard").output
    assert "anthropic/claude-sonnet-5.5" in board
    assert "noisy" in board


def test_search_index_is_refreshed_when_files_change(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _run(workspace, "note", "unity", "First note about shaders.")
    assert "shaders" in _run(workspace, "search", "shaders").output

    _run(workspace, "note", "unity", "Second note about lightmaps.")

    assert "lightmaps" in _run(workspace, "search", "lightmaps").output
    with closing(sqlite3.connect(workspace.store / "index.sqlite")) as connection:
        assert connection.execute("SELECT count(*) FROM meta").fetchone()[0] == 1


def test_search_survives_a_damaged_index_and_odd_queries(workspace, openrouter):
    _init(workspace)
    _run(workspace, "note", "unity", 'Quotes "inside" and AND/OR words.')
    (workspace.store / "index.sqlite").write_text("not a database", encoding="utf-8")

    result = _run(workspace, "search", '"inside" AND')

    assert result.exit_code == 0, result.output
    assert "notes.md" in result.output


def test_show_unknown_topic(workspace):
    _init(workspace)

    result = _run(workspace, "show", "nothing")

    assert result.exit_code == 1
    assert "No topic named 'nothing'" in result.output


def test_empty_note_is_refused(workspace):
    _init(workspace)

    assert _run(workspace, "note", "unity", "  ").exit_code == 1


def test_leaderboard_with_no_runs(workspace):
    _init(workspace)

    assert "No rankings yet" in _run(workspace, "leaderboard").output


def test_search_works_without_full_text_support(workspace, monkeypatch):
    _init(workspace)
    monkeypatch.setattr(library, "_fts_available", lambda connection: False)
    _run(workspace, "note", "unity", "Plain text fallback about shaders.")

    result = _run(workspace, "search", "fallback shaders")

    assert "notes.md" in result.output
    assert _run(workspace, "search", "missingword").output.strip() == "Nothing found."


def test_index_connections_are_closed(workspace, monkeypatch):
    """Windows cannot delete a file that is still open, so every connection must close."""
    _init(workspace)
    opened = []
    real_connect = sqlite3.connect

    def tracking_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(library.sqlite3, "connect", tracking_connect)
    _run(workspace, "note", "unity", "About shaders.")
    _run(workspace, "search", "shaders")
    _run(workspace, "note", "unity", "About lightmaps.")
    _run(workspace, "search", "lightmaps")

    assert len(opened) >= 3
    for connection in opened:
        try:
            connection.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            continue  # closed, as it should be
        raise AssertionError("a connection to the search index was left open")


def test_a_full_run_stopped_after_research_is_still_shown_as_full(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    from conftest import failure

    for model in ("anthropic/claude-sonnet-5.5", "openai/gpt-6.1-sol"):
        openrouter.reply(model, failure(402, "no credit"), stage="research")
    _run(workspace, "ask", "Q?", "--full", "-t", "os")
    openrouter.replies.clear()  # credit restored before the quick run
    _run(workspace, "ask", "Quick?", "-t", "os")

    show = _run(workspace, "show", "os").output
    assert "(full, stopped before the one-page answer)" in show
    assert "(quick)" in show
    row = [line.split() for line in _run(workspace, "topics").output.splitlines()][1]
    assert row[:3] == ["os", "2", "1"]
