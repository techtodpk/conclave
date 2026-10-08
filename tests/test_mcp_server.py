import asyncio
import sys

import pytest
from typer.testing import CliRunner

from conclave.cli import app
from conftest import PAGE_A, failure

pytest.importorskip("mcp")

from mcp import ClientSession, StdioServerParameters, stdio_client  # noqa: E402
from mcp.server.mcpserver.exceptions import ToolError  # noqa: E402
from mcp.types import Implementation  # noqa: E402

from conclave.mcp_server import create_server  # noqa: E402

runner = CliRunner()
SONNET = "anthropic/claude-sonnet-5.5"


def _init(workspace):
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0, result.output


def _call(workspace, tool, **arguments):
    server = create_server(workspace.config)
    result = asyncio.run(server.call_tool(tool, arguments))
    return result.content[0].text


def test_the_server_offers_six_tools_and_says_which_only_read(workspace):
    _init(workspace)
    tools = asyncio.run(create_server(workspace.config).list_tools())

    by_name = {t.name: t for t in tools}
    assert set(by_name) == {
        "list_topics",
        "search_research",
        "get_topic",
        "get_run",
        "ask_council",
        "add_note",
    }
    for name in ("list_topics", "search_research", "get_topic", "get_run"):
        assert by_name[name].annotations.read_only_hint is True
    assert by_name["ask_council"].annotations.read_only_hint is False
    assert "costs the user money" in by_name["ask_council"].description.lower()
    assert "ctx" not in by_name["add_note"].input_schema["properties"]


def test_quick_ask_by_default_saves_the_run_and_reports_the_cost(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    text = _call(workspace, "ask_council", question="Why is the sky blue?", topic="sky")

    assert openrouter.asked == [SONNET]
    assert all("tools" not in body for body in openrouter.chat_requests)
    assert "Answer from anthropic/claude-sonnet-5.5." in text
    assert "Conclave quick run on topic 'sky'" in text
    assert "of the $0.10 cap for quick runs" in text
    assert len(list((workspace.store / "topics" / "sky" / "runs").iterdir())) == 1


def test_full_ask_runs_the_whole_council_with_search_and_checks(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    text = _call(workspace, "ask_council", question="Why is the sky blue?", topic="sky", full=True)

    assert openrouter.asked_in("check") == [SONNET]
    assert "## Sources" in text
    assert "Key claims checked against sources: 1 of 3 verified" in text
    assert "The topic's memory was updated:" in text


def test_refusals_come_back_as_tool_errors_and_nothing_is_sent(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    text = workspace.config.read_text(encoding="utf-8")
    workspace.config.write_text(text.replace("full_run_usd = 1.00", "full_run_usd = 0.01"), "utf-8")

    with pytest.raises(ToolError, match="above the \\$0.01 cap for full runs"):
        _call(workspace, "ask_council", question="Q?", full=True)
    with pytest.raises(ToolError, match="question is empty"):
        _call(workspace, "ask_council", question="  ")
    assert openrouter.chat_requests == []


def test_missing_key_is_a_tool_error(workspace, openrouter):
    _init(workspace)

    with pytest.raises(ToolError, match="No OpenRouter API key found"):
        _call(workspace, "ask_council", question="Q?")


def test_reading_tools_show_topics_claims_runs_and_search(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _call(workspace, "ask_council", question="Why is the sky blue?", topic="sky", full=True)
    runner.invoke(app, ["note", "sky", "I care about sunsets.", "--config", str(workspace.config)])

    topics = _call(workspace, "list_topics")
    assert "sky | 1 | 1 | 1 | 1 |" in topics

    topic = _call(workspace, "get_topic", topic="Sky")
    assert "- C1: A claim. [agreed but unchecked]" in topic
    assert "- D1: Whether the claim holds everywhere." in topic
    assert "I care about sunsets." in topic

    final = _call(workspace, "get_run", topic="sky")
    assert final.startswith("# Why is the sky blue?")
    assert PAGE_A in final

    found = _call(workspace, "search_research", query="sunsets")
    assert "notes.md [notes]" in found


def test_reading_tools_explain_what_is_missing(workspace):
    _init(workspace)

    assert _call(workspace, "list_topics") == "No topics yet."
    assert _call(workspace, "search_research", query="anything") == "Nothing found."
    with pytest.raises(ToolError, match="No topic named 'nope'"):
        _call(workspace, "get_topic", topic="nope")


def test_get_run_cannot_leave_the_topic_folder(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _call(workspace, "ask_council", question="Q?", topic="sky")

    for bad in ("../../..", "..", "x/../..", "missing"):
        with pytest.raises(ToolError, match="No run named"):
            _call(workspace, "get_run", topic="sky", run=bad)


def test_notes_added_through_mcp_are_marked_as_the_assistants(workspace):
    _init(workspace)

    text = _call(workspace, "add_note", topic="sky", note="  Use   metric units. ")

    assert "Added to" in text
    notes = (workspace.store / "topics" / "sky" / "notes.md").read_text(encoding="utf-8")
    assert "Use metric units. (added by an assistant via MCP)" in notes


def test_config_problem_is_reported_by_every_tool(workspace):
    workspace.config.parent.mkdir(parents=True)
    workspace.config.write_text("[store\n", "utf-8")

    with pytest.raises(ToolError, match="Config problem"):
        _call(workspace, "list_topics")


def test_ask_council_quick_run_failure_explains_why(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.reply(SONNET, failure(401))

    with pytest.raises(ToolError, match="No model answered"):
        _call(workspace, "ask_council", question="Q?")


def test_real_stdio_session_names_the_client_on_notes(workspace):
    """Start `conclave mcp` as Claude Desktop would, and talk to it over stdio."""
    _init(workspace)

    async def session():
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "conclave", "mcp", "--config", str(workspace.config)],
        )
        async with stdio_client(params) as (read, write):
            client = Implementation(name="test-client", version="1")
            async with ClientSession(read, write, client_info=client) as s:
                await s.initialize()
                tools = await s.list_tools()
                added = await s.call_tool("add_note", {"topic": "sky", "note": "Hello."})
                missing = await s.call_tool("get_topic", {"topic": "nope"})
                return [t.name for t in tools.tools], added, missing

    names, added, missing = asyncio.run(asyncio.wait_for(session(), 60))

    assert "ask_council" in names
    assert added.is_error is False
    assert missing.is_error is True
    notes = (workspace.store / "topics" / "sky" / "notes.md").read_text(encoding="utf-8")
    assert "Hello. (added by test-client via MCP)" in notes


def test_mcp_command_explains_a_missing_extra(workspace, monkeypatch):
    _init(workspace)
    monkeypatch.setitem(sys.modules, "conclave.mcp_server", None)

    result = runner.invoke(app, ["mcp", "--config", str(workspace.config)])

    assert result.exit_code == 1
    assert 'pip install -e ".[mcp]"' in result.output
