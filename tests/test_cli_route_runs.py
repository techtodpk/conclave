"""Whole runs with council seats on the user's own plan (route "cli")."""

import json

import pytest
from typer.testing import CliRunner

import conclave.cli_tools as cli_tools
from conclave.cli import app
from conclave.cli_tools import Ran
from conftest import PAGE_A, default_reply, stage_of

runner = CliRunner()
SONNET = "anthropic/claude-sonnet-5.5"


def _init(workspace):
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0, result.output


def _ask(workspace, *args):
    return runner.invoke(app, ["ask", *args, "--config", str(workspace.config)])


def _route_to_cli(workspace, line):
    text = workspace.config.read_text(encoding="utf-8")
    assert line in text
    workspace.config.write_text(
        text.replace(line, line.replace('route = "api"', 'route = "cli"')), encoding="utf-8"
    )


@pytest.fixture
def claude_code(monkeypatch):
    """A stand-in for Claude Code that answers like the simulated OpenRouter models."""
    calls = []

    def run(argv, stdin, cwd, timeout):
        system = argv[argv.index("--system-prompt") + 1]
        searching = argv[argv.index("--tools") + 1] == "WebSearch"
        body = {
            "model": SONNET,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": stdin},
            ],
        }
        if searching:
            body["tools"] = [{"type": "web_search"}]
        calls.append({"stage": stage_of(body), "argv": argv, "searching": searching})
        reply = json.loads(default_reply(body).content)
        text = reply["choices"][0]["message"]["content"]
        result = {
            "type": "result",
            "subtype": "success",
            "is_error": False,
            "result": text,
            "modelUsage": {"claude-sonnet-5-5": {"inputTokens": 900, "outputTokens": 300}},
            "total_cost_usd": 0.03,
        }
        return Ran(0, json.dumps(result), "")

    monkeypatch.setattr(cli_tools, "find", lambda tool: f"/usr/bin/{tool.command}")
    monkeypatch.setattr(cli_tools, "run_process", run)
    return calls


def test_full_run_with_one_member_on_its_plan(workspace, openrouter, claude_code):
    _init(workspace)
    workspace.set_key()
    _route_to_cli(workspace, '    { model = "anthropic/claude-sonnet-5.5", route = "api" },')

    result = _ask(workspace, "Why is the sky blue?", "--full", "-t", "sky")

    assert result.exit_code == 0, result.output
    # Claude answered and reviewed through its own tool, and was never sent to OpenRouter
    # as a member; the chairman and checker still use OpenRouter.
    assert [c["stage"] for c in claude_code] == ["research", "critique"]
    assert claude_code[0]["searching"] and not claude_code[1]["searching"]
    assert SONNET not in openrouter.asked_in("research")
    assert SONNET not in openrouter.asked_in("critique")
    assert SONNET in openrouter.asked_in("synthesis")

    (meta_path,) = workspace.store.glob("topics/sky/runs/*/meta.json")
    calls = json.loads(meta_path.read_text(encoding="utf-8"))["calls"]
    research = next(c for c in calls if c["stage"] == "research" and c["model"] == SONNET)
    assert research["route"] == "cli"
    assert research["cost_usd"] == 0.0 and research["cost_source"] == "plan"
    assert research["sources_cited"] == 1  # the Markdown link in its answer
    assert research["usage"]["tool"] == "claude"
    sources = json.loads((meta_path.parent / "sources.json").read_text(encoding="utf-8"))
    assert PAGE_A in json.dumps(sources)


def test_quick_run_on_a_plan_needs_no_openrouter_key(workspace, openrouter, claude_code):
    _init(workspace)
    _route_to_cli(workspace, 'chairman = { model = "anthropic/claude-sonnet-5.5", route = "api" }')

    result = _ask(workspace, "Why is the sky blue?", "--profile", "lean")

    assert result.exit_code == 0, result.output
    assert len(claude_code) == 1 and not claude_code[0]["searching"]
    assert openrouter.chat_requests == []


def test_seats_on_a_plan_do_not_count_against_the_cap(workspace, openrouter, claude_code):
    from conclave.budget import research_worst_case, worst_case_cost
    from conclave.catalog import ModelInfo
    from conclave.config import Member

    catalog = {SONNET: ModelInfo(SONNET, "Sonnet", 0.001, 0.001, 1_000_000)}
    on_plan = [Member(SONNET, route="cli")]
    assert worst_case_cost(on_plan, catalog, 10_000, 1_000) == 0.0
    assert research_worst_case(on_plan, catalog, 10_000, 1_000, searches=3) == 0.0
    assert worst_case_cost([Member(SONNET)], catalog, 10_000, 1_000) > 0


def test_tools_command_shows_what_is_installed(monkeypatch):
    def find(tool):
        return "/usr/bin/claude" if tool.command == "claude" else None

    monkeypatch.setattr(cli_tools, "find", find)
    monkeypatch.setattr(
        cli_tools,
        "run_process",
        lambda argv, stdin, cwd, timeout: Ran(0, "2.1.296 (Claude Code)\n", ""),
    )

    result = runner.invoke(app, ["tools"])

    assert result.exit_code == 0, result.output
    assert "Installed: /usr/bin/claude" in result.output
    assert "Version:   2.1.296 (Claude Code)" in result.output
    assert result.output.count("Not installed.") == 2
    assert "npm install -g @openai/codex" in result.output


def test_config_says_which_seats_run_on_a_plan(workspace):
    _init(workspace)
    _route_to_cli(workspace, '    { model = "openai/gpt-6.1-sol", route = "api" },')

    result = runner.invoke(app, ["config", "--config", str(workspace.config)])

    assert "openai/gpt-6.1-sol [on your plan through Codex CLI]" in result.output
