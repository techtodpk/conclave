"""Command-line routes: Claude Code, Codex CLI and Antigravity CLI on the user's own plan.

The sample outputs below are trimmed from real runs of each tool in October 2026.
"""

import asyncio
import json

import pytest

import conclave.cli_tools as cli_tools
from conclave.cli_tools import (
    MAX_ARGUMENT_CHARS,
    NO_TOOLS,
    SEARCH_ONLY,
    TOOLS,
    CliClient,
    Ran,
    cited_links,
    read_agy,
    read_claude,
    read_codex,
    tool_model,
)
from conclave.client import ModelError
from conclave.config import ConfigError, Member, parse_member

SONNET = Member("anthropic/claude-sonnet-5.5", route="cli")
GPT = Member("openai/gpt-6.1-sol", route="cli")
GEMINI = Member("google/gemini-3.8-flash", route="cli")
MESSAGES = [
    {"role": "system", "content": "You are one member of a research council."},
    {"role": "user", "content": "Question: what is the current stable Python?"},
]

CLAUDE_OK = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": False,
        "num_turns": 2,
        "total_cost_usd": 0.0256313,
        "result": (
            "The newest stable release I found is **Python 3.14.6**.\n\nSources:\n"
            "- [Python Source Releases (python.org)](https://www.python.org/downloads/source/)\n"
            "- [The Latest Version of Python](https://phoenixnap.com/kb/latest-python-version).\n"
            "- [Again](https://www.python.org/downloads/source/)"
        ),
        "modelUsage": {
            "claude-sonnet-5-5": {
                "inputTokens": 4,
                "outputTokens": 400,
                "cacheReadInputTokens": 1616,
                "cacheCreationInputTokens": 2463,
                "webSearchRequests": 0,
                "thinkingTokens": 0,
            },
            "claude-haiku-5-5": {
                "inputTokens": 12927,
                "outputTokens": 634,
                "webSearchRequests": 1,
                "thinkingTokens": 0,
            },
        },
    }
)
CLAUDE_LOGGED_OUT = json.dumps(
    {
        "type": "result",
        "subtype": "success",
        "is_error": True,
        "result": "Not logged in · Please run /login",
    }
)


def _codex(*events):
    return "\n".join(json.dumps(e) for e in events)


CODEX_OK = _codex(
    {"type": "thread.started", "thread_id": "t1"},
    {"type": "turn.started"},
    {
        "type": "item.completed",
        "item": {"type": "agent_message", "text": "I'll check Python's downloads page."},
    },
    {
        "type": "item.completed",
        "item": {
            "type": "web_search",
            "action": {"type": "search", "query": "python latest release"},
            "results": [
                {
                    "url": "https://www.python.org/downloads/release/python-3150/",
                    "title": "Python 3.15.0",
                    "snippet": "Python 3.15.0 is the newest major release",
                }
            ],
        },
    },
    {
        "type": "item.completed",
        "item": {
            "type": "web_search",
            "action": {"type": "open_page", "url": "https://www.python.org/downloads/"},
            "results": [],
        },
    },
    {
        "type": "item.completed",
        "item": {
            "type": "agent_message",
            "text": "It is **Python 3.15.0**, per the [release page]"
            "(https://www.python.org/downloads/release/python-3150/).",
        },
    },
    {
        "type": "turn.completed",
        "usage": {
            "input_tokens": 64456,
            "cached_input_tokens": 47488,
            "output_tokens": 157,
            "reasoning_output_tokens": 12,
        },
    },
)
CODEX_LIMIT = _codex(
    {"type": "thread.started", "thread_id": "t2"},
    {"type": "turn.started"},
    {"type": "error", "message": "You've hit your usage limit. Try again at 4:16 AM."},
    {
        "type": "turn.failed",
        "error": {"message": "You've hit your usage limit. Try again at 4:16 AM."},
    },
)

AGY_OK = json.dumps(
    {
        "conversation_id": "c1",
        "status": "SUCCESS",
        "response": "The latest stable Python is **3.15.0**.\n\n* [Python.org Downloads]"
        "(https://vertexaisearch.cloud.google.com/grounding-api-redirect/AUZIYQG9)\n",
        "num_turns": 1,
        "usage": {"input_tokens": 36774, "output_tokens": 1253, "thinking_tokens": 982},
    }
)
AGY_DENIED = json.dumps(
    {
        "status": "SUCCESS",
        "response": "",
        "denied_actions": [{"action": "read_url", "display_name": "ReadUrlContent"}],
    }
)


# --- reading each tool's output ---------------------------------------------------------


def test_claude_answer_tokens_searches_and_cited_pages():
    done = read_claude(Ran(0, CLAUDE_OK, ""))

    assert done.text.startswith("The newest stable release")
    assert done.prompt_tokens == 4 + 1616 + 2463 + 12927
    assert done.completion_tokens == 400 + 634
    assert done.searches == 1  # Claude Code searches through a smaller model
    assert [s.url for s in done.sources] == [
        "https://www.python.org/downloads/source/",
        "https://phoenixnap.com/kb/latest-python-version",
    ]
    assert done.usage["api_value_usd"] == pytest.approx(0.0256313)


def test_claude_error_is_passed_on_in_its_own_words():
    with pytest.raises(ModelError, match="Not logged in"):
        read_claude(Ran(1, CLAUDE_LOGGED_OUT, ""))


def test_codex_final_message_searches_and_excerpts():
    done = read_codex(Ran(0, CODEX_OK, ""))

    assert done.text.startswith("It is **Python 3.15.0**")  # not the "I'll check" note
    assert done.searches == 1  # opening a page is not a search
    (source,) = done.sources
    assert source.url == "https://www.python.org/downloads/release/python-3150/"
    assert source.excerpt == "Python 3.15.0 is the newest major release"
    assert (done.prompt_tokens, done.completion_tokens, done.reasoning_tokens) == (64456, 157, 12)


def test_codex_usage_limit_is_passed_on():
    with pytest.raises(ModelError, match="usage limit. Try again at 4:16 AM"):
        read_codex(Ran(1, CODEX_LIMIT, ""))


def test_antigravity_answer_and_redirect_link():
    done = read_agy(Ran(0, AGY_OK, ""))

    assert "3.15.0" in done.text
    assert done.sources[0].url.startswith("https://vertexaisearch.cloud.google.com/")
    assert done.searches is None  # not reported
    assert (done.prompt_tokens, done.completion_tokens) == (36774, 1253)


def test_antigravity_blocked_tool_is_explained():
    with pytest.raises(ModelError, match="tried to use read_url"):
        read_agy(Ran(0, AGY_DENIED, ""))


def test_output_that_is_not_json_says_what_the_tool_printed():
    with pytest.raises(ModelError, match="did not reply with JSON: command not understood"):
        read_agy(Ran(2, "", "command not understood"))


def test_cited_links_keep_order_and_drop_repeats_and_punctuation():
    text = "See [A](https://a.example/x). Then [B](http://b.example/y), and [A again](https://a.example/x)."
    assert [(s.title, s.url) for s in cited_links(text)] == [
        ("A", "https://a.example/x"),
        ("B", "http://b.example/y"),
    ]
    assert cited_links("[not a link](ftp://c.example)") == ()


# --- building each command ----------------------------------------------------------------


def _command(tool, searches, user="Q?", reasoning="low", program=None):
    return cli_tools._command(
        TOOLS[tool], program or TOOLS[tool].command, "m", "SYSTEM", user, searches, reasoning
    )


def test_claude_command_allows_only_web_search_and_skips_user_setup():
    argv, stdin = _command("anthropic", searches=3)

    assert stdin == "Q?"
    assert argv[argv.index("--system-prompt") + 1] == f"SYSTEM\n\n{SEARCH_ONLY}"
    assert argv[argv.index("--tools") + 1] == "WebSearch"
    assert argv[argv.index("--allowedTools") + 1] == "WebSearch"
    for flag in ("--strict-mcp-config", "--no-session-persistence", "--disable-slash-commands"):
        assert flag in argv
    assert argv[argv.index("--permission-prompts") + 1] == "none"
    assert argv[argv.index("--effort") + 1] == "low"


def test_claude_command_without_search_has_no_tools():
    argv, _ = _command("anthropic", searches=0, reasoning="none")

    assert argv[argv.index("--tools") + 1] == ""
    assert "--allowedTools" not in argv
    assert argv[argv.index("--system-prompt") + 1].endswith(NO_TOOLS)
    assert argv[argv.index("--effort") + 1] == "low"


def test_codex_command_is_read_only_and_searches_only_when_asked():
    argv, stdin = _command("openai", searches=2)

    assert argv[1:4] == ["-a", "never", "--search"]
    assert argv[argv.index("exec") + 1] == "-"  # the prompt comes on standard input
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert "--ephemeral" in argv and "--skip-git-repo-check" in argv
    assert stdin == f"SYSTEM\n\n{SEARCH_ONLY}\n\nQ?"
    assert "--search" not in _command("openai", searches=0)[0]


def test_antigravity_command_carries_the_prompt_and_refuses_one_too_long():
    argv, stdin = _command("google", searches=1)

    assert argv[argv.index("-p") + 1] == f"SYSTEM\n\n{SEARCH_ONLY}\n\nQ?"
    assert stdin == ""
    with pytest.raises(ModelError, match="longer than one command line"):
        _command("google", searches=1, user="x" * MAX_ARGUMENT_CHARS)


def test_windows_cmd_wrapper_is_refused_for_multi_line_text():
    with pytest.raises(ModelError, match=r"\.cmd wrapper"):
        _command("anthropic", searches=0, program=r"C:\npm\claude.cmd")


def test_model_names_each_tool_expects():
    assert tool_model(SONNET) == "claude-sonnet-5-5"
    assert tool_model(GPT) == "gpt-6.1-sol"
    assert tool_model(GEMINI, "medium") == "gemini-3.8-flash-medium"
    assert tool_model(GEMINI, "none") == "gemini-3.8-flash-low"
    override = Member("google/gemini-3.1-pro", route="cli", cli_model="gemini-3.1-pro-high")
    assert tool_model(override) == "gemini-3.1-pro-high"


def test_config_reads_cli_model():
    member = parse_member({"model": "google/gemini-3.1-pro", "route": "cli", "cli_model": " x "})
    assert member == Member("google/gemini-3.1-pro", "cli", "x")
    with pytest.raises(ConfigError, match="cli_model"):
        parse_member({"model": "google/gemini-3.1-pro", "route": "cli", "cli_model": 3})


# --- the client -----------------------------------------------------------------------------


def _client(output, code=0, seen=None, installed=True):
    def runner(argv, stdin, cwd, timeout):
        if seen is not None:
            seen.update(argv=argv, stdin=stdin, cwd=cwd, timeout=timeout)
        return Ran(code, output, "")

    return CliClient(
        runner=runner, finder=lambda tool: f"/bin/{tool.command}" if installed else None
    )


def test_client_answers_at_no_cost_against_the_caps():
    seen = {}
    done = asyncio.run(_client(CLAUDE_OK, seen=seen).complete(SONNET, MESSAGES, 500, searches=3))

    assert done.cost_usd == 0.0
    assert done.usage["tool"] == "claude" and done.usage["model"] == "claude-sonnet-5-5"
    assert len(done.sources) == 2
    assert seen["argv"][0] == "/bin/claude"
    assert seen["stdin"] == MESSAGES[1]["content"]
    assert seen["cwd"] != "" and seen["timeout"] == cli_tools.TIMEOUT_SECONDS


def test_codex_runs_in_its_own_empty_folder():
    seen = {}
    asyncio.run(_client(CODEX_OK, seen=seen).complete(GPT, MESSAGES, 500))

    assert seen["argv"][seen["argv"].index("-C") + 1] == seen["cwd"]


def test_client_errors_name_the_tool():
    with pytest.raises(ModelError, match="^Codex CLI: You've hit your usage limit"):
        asyncio.run(_client(CODEX_LIMIT, code=1).complete(GPT, MESSAGES, 500))


def test_client_says_how_to_install_a_missing_tool():
    with pytest.raises(ModelError) as caught:
        asyncio.run(_client(AGY_OK, installed=False).complete(GEMINI, MESSAGES, 500))
    message = str(caught.value)
    assert "`agy` command was not found" in message
    assert "antigravity.google/cli/install.ps1" in message
    assert 'route = "api"' in message


def test_vendor_without_a_tool_is_refused():
    with pytest.raises(ModelError, match="no command-line tool for 'deepseek'"):
        asyncio.run(_client("").complete(Member("deepseek/v4", route="cli"), MESSAGES, 500))


def test_timeout_is_reported_plainly(monkeypatch):
    def slow(argv, stdin, cwd, timeout):
        raise ModelError(f"it took longer than {int(timeout)} seconds and was stopped")

    client = CliClient(runner=slow, finder=lambda tool: "/bin/agy", timeout=7)
    with pytest.raises(ModelError, match="^Antigravity CLI: it took longer than 7 seconds"):
        asyncio.run(client.complete(GEMINI, MESSAGES, 500))
