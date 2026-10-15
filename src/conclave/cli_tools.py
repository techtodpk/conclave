"""Council members on the user's own plan, through each vendor's command-line tool.

A seat with `route = "cli"` is answered by Claude Code, Codex CLI or Antigravity CLI instead
of OpenRouter (decision 0014). Each call runs the tool once, non-interactively, in an empty
temporary folder, with web search as its only tool, and reads its JSON output. The call costs
nothing against Conclave's caps; it draws on the user's plan instead.
"""

from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass

from conclave.client import Completion, ModelError, Source
from conclave.config import Member

# The longest one call may take before it is stopped. Searching and writing a long answer
# through a command-line agent can take a few minutes.
TIMEOUT_SECONDS = 300

# Windows refuses command lines longer than 32,767 characters.
MAX_ARGUMENT_CHARS = 30_000

SEARCH_ONLY = (
    "Use web search only. Do not open or read pages, and do not run commands or touch files."
)
NO_TOOLS = "Do not use any tools: answer from what is in this message."


@dataclass(frozen=True)
class Tool:
    vendor: str  # the part of the model id before the slash
    command: str  # the program to run
    name: str  # what the user knows it as
    install: str  # how to install it
    login: str  # how to sign in once


TOOLS = {
    "anthropic": Tool(
        "anthropic",
        "claude",
        "Claude Code",
        "on Windows `irm https://claude.ai/install.ps1 | iex`, on macOS and Linux "
        "`curl -fsSL https://claude.ai/install.sh | bash`",
        "run `claude` once and type /login",
    ),
    "openai": Tool(
        "openai",
        "codex",
        "Codex CLI",
        "`npm install -g @openai/codex`",
        "run `codex` once and choose Sign in with ChatGPT",
    ),
    "google": Tool(
        "google",
        "agy",
        "Antigravity CLI",
        "on Windows `irm https://antigravity.google/cli/install.ps1 | iex`, on macOS and Linux "
        "`curl -fsSL https://antigravity.google/cli/install.sh | bash`",
        "run `agy` once and sign in with Google",
    ),
}

# Reasoning levels in the config, as each tool spells them.
_CLAUDE_EFFORT = {"none": "low", "minimal": "low", "low": "low", "medium": "medium", "high": "high"}
_CODEX_EFFORT = {
    "none": "minimal",
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "high": "high",
}
_AGY_LEVEL = {"none": "low", "minimal": "low", "low": "low", "medium": "medium", "high": "high"}


def tool_for(member: Member) -> Tool:
    """The command-line tool that answers for this model. Raises ModelError if there is none."""
    tool = TOOLS.get(member.vendor)
    if tool is None:
        names = ", ".join(f"{t.vendor} ({t.name})" for t in TOOLS.values())
        raise ModelError(
            f"{member.model} is set to route 'cli', but there is no command-line tool for "
            f"'{member.vendor}' models. The cli route works for {names}. "
            'Set route = "api" for this model.'
        )
    return tool


def tool_model(member: Member, reasoning: str = "low") -> str:
    """The model name the tool expects. `cli_model` in the config overrides the guess."""
    if member.cli_model:
        return member.cli_model
    name = member.model.split("/", 1)[1]
    if member.vendor == "anthropic":
        return name.replace(".", "-")  # claude-sonnet-5.5 -> claude-sonnet-5-5
    if member.vendor == "google":
        return f"{name}-{_AGY_LEVEL.get(reasoning, 'low')}"  # gemini-3.8-flash-low
    return name


def find(tool: Tool) -> str | None:
    """The full path to the tool's program, or None if it is not installed."""
    return shutil.which(tool.command)


def not_installed(tool: Tool, member: Member) -> str:
    return (
        f"{member.model} is set to run on your own plan through {tool.name}, but the "
        f"`{tool.command}` command was not found. Install it ({tool.install}), then "
        f'{tool.login}. Or set route = "api" for this model to use OpenRouter instead.'
    )


# --- running a tool -------------------------------------------------------------------


@dataclass(frozen=True)
class Ran:
    code: int
    out: str
    err: str


Runner = Callable[[list[str], str, str, float], Ran]


def run_process(argv: list[str], stdin: str, cwd: str, timeout: float) -> Ran:
    """Run a program to the end and capture its output. Raises ModelError on timeout."""
    try:
        done = subprocess.run(
            argv,
            input=stdin.encode("utf-8"),
            capture_output=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        raise ModelError(f"it took longer than {int(timeout)} seconds and was stopped") from None
    except OSError as error:
        raise ModelError(f"it could not be started ({error})") from None
    return Ran(
        done.returncode,
        done.stdout.decode("utf-8", errors="replace"),
        done.stderr.decode("utf-8", errors="replace"),
    )


class CliClient:
    """Answers for seats with route 'cli', through the vendor's own command-line tool."""

    def __init__(
        self,
        reasoning: str = "low",
        timeout: float = TIMEOUT_SECONDS,
        runner: Runner | None = None,
        finder: Callable[[Tool], str | None] | None = None,
    ) -> None:
        self._reasoning = reasoning
        self._timeout = timeout
        # Looked up at call time, so tests can replace the module's find and run_process.
        self._runner = runner
        self._finder = finder

    async def complete(
        self,
        member: Member,
        messages: list[dict[str, str]],
        max_tokens: int,
        searches: int = 0,
    ) -> Completion:
        """`max_tokens` cannot be passed to these tools; the prompts ask for a set length."""
        tool = tool_for(member)
        program = (self._finder or find)(tool)
        if program is None:
            raise ModelError(not_installed(tool, member))
        system, user = _split(messages)
        model = tool_model(member, self._reasoning)
        argv, stdin = _command(tool, program, model, system, user, searches, self._reasoning)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="conclave-") as workdir:
            if tool.vendor == "openai":
                argv += ["-C", workdir]
            try:
                runner = self._runner or run_process
                ran = await asyncio.to_thread(runner, argv, stdin, workdir, self._timeout)
            except ModelError as error:
                raise ModelError(f"{tool.name}: {error}") from None
        seconds = time.monotonic() - started
        try:
            done = _READERS[tool.vendor](ran)
        except ModelError as error:
            raise ModelError(f"{tool.name}: {error}") from None
        return Completion(
            text=done.text,
            prompt_tokens=done.prompt_tokens,
            completion_tokens=done.completion_tokens,
            cost_usd=0.0,  # paid by the user's plan, not counted against the caps
            seconds=seconds,
            reasoning_tokens=done.reasoning_tokens,
            searches=done.searches,
            sources=done.sources,
            usage={"tool": tool.command, "model": model, **done.usage},
        )


def _split(messages: list[dict[str, str]]) -> tuple[str, str]:
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = "\n\n".join(m["content"] for m in messages if m["role"] != "system")
    return system, rest


def _command(
    tool: Tool,
    program: str,
    model: str,
    system: str,
    user: str,
    searches: int,
    reasoning: str,
) -> tuple[list[str], str]:
    """The program's arguments and what to send on its standard input."""
    rule = SEARCH_ONLY if searches else NO_TOOLS
    if tool.vendor == "anthropic":
        instructions = f"{system}\n\n{rule}"
        _safe_for_wrapper(program, instructions)
        argv = [
            program,
            "-p",
            "--output-format",
            "json",
            "--model",
            model,
            "--effort",
            _CLAUDE_EFFORT.get(reasoning, "low"),
            "--system-prompt",
            instructions,
            "--permission-prompts",
            "none",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--disable-slash-commands",
        ]
        if searches:
            argv += ["--tools", "WebSearch", "--allowedTools", "WebSearch"]
        else:
            argv += ["--tools", ""]
        return argv, user
    prompt = f"{system}\n\n{rule}\n\n{user}"
    if tool.vendor == "openai":
        argv = [program, "-a", "never"]
        if searches:
            argv.append("--search")
        argv += [
            "exec",
            "-",
            "--json",
            "--skip-git-repo-check",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{_CODEX_EFFORT.get(reasoning, "low")}"',
        ]
        return argv, prompt
    # Antigravity takes the prompt as an argument.
    if len(prompt) > MAX_ARGUMENT_CHARS:
        raise ModelError(
            f"Antigravity CLI: this prompt is {len(prompt):,} characters, longer than one "
            "command line can carry. Lower run.max_answer_tokens, use fewer members, or set "
            'route = "api" for this model.'
        )
    _safe_for_wrapper(program, prompt)
    argv = [program, "-p", prompt, "--output-format", "json", "--model", model, "--sandbox"]
    return argv, ""


def _safe_for_wrapper(program: str, text: str) -> None:
    """Refuse to pass multi-line text through a Windows .cmd or .bat wrapper.

    Such wrappers re-read their arguments through cmd.exe, which can split or reinterpret
    them. The tools' own installers put a real program on PATH instead.
    """
    if program.lower().endswith((".cmd", ".bat")) and any(c in text for c in '\n"%&|<>^'):
        raise ModelError(
            f"`{program}` is a .cmd wrapper, which cannot safely carry Conclave's prompts. "
            "Install the tool with its own installer so a real program is on PATH."
        )


# --- reading each tool's output ---------------------------------------------------------

_LINK = re.compile(r"\[([^\]\n]{1,300})\]\((https?://[^\s)]+)\)")


@dataclass
class _Read:
    text: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    searches: int | None = None
    sources: tuple[Source, ...] = ()
    usage: dict | None = None

    def __post_init__(self) -> None:
        self.usage = self.usage or {}


def cited_links(text: str, excerpts: dict[str, str] | None = None) -> tuple[Source, ...]:
    """The pages an answer cites as Markdown links, one per URL, in the order first cited."""
    found: dict[str, Source] = {}
    for title, url in _LINK.findall(text):
        url = url.rstrip(".,;:")
        if url not in found:
            found[url] = Source(url=url, title=title.strip(), excerpt=(excerpts or {}).get(url, ""))
    return tuple(found.values())


def _whole(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0


def _json_object(out: str, err: str = "") -> dict:
    """The tool's JSON reply: the last line of its output that is a JSON object."""
    for line in reversed(out.strip().splitlines()):
        line = line.strip().lstrip("﻿")
        if line.startswith("{"):
            try:
                value = json.loads(line)
            except ValueError:
                continue
            if isinstance(value, dict):
                return value
    try:
        value = json.loads(out.strip().lstrip("﻿"))
    except ValueError:
        value = None
    if isinstance(value, dict):
        return value
    raise ModelError(_failure("it did not reply with JSON", err or out))


def _failure(what: str, err: str) -> str:
    tail = " ".join(err.strip().split())[-300:]
    return f"{what}: {tail}" if tail else what


def _answer(text: object) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ModelError("it returned an empty answer")
    return text.strip()


def read_claude(ran: Ran) -> _Read:
    data = _json_object(ran.out or ran.err, ran.err)
    if data.get("is_error") or data.get("subtype") not in (None, "success"):
        message = data.get("result") or data.get("subtype") or "it reported an error"
        raise ModelError(str(message))
    text = _answer(data.get("result"))
    models = data.get("modelUsage") if isinstance(data.get("modelUsage"), dict) else {}
    prompt = completion = reasoning = searches = 0
    for figures in models.values():
        if not isinstance(figures, dict):
            continue
        prompt += sum(
            _whole(figures.get(k))
            for k in ("inputTokens", "cacheReadInputTokens", "cacheCreationInputTokens")
        )
        completion += _whole(figures.get("outputTokens"))
        reasoning += _whole(figures.get("thinkingTokens"))
        searches += _whole(figures.get("webSearchRequests"))
    value = data.get("total_cost_usd")
    usage = {"models": sorted(models), "turns": data.get("num_turns")}
    if isinstance(value, int | float) and not isinstance(value, bool):
        usage["api_value_usd"] = value  # what the calls would cost at API prices
    return _Read(text, prompt, completion, reasoning, searches, cited_links(text), usage)


def read_codex(ran: Ran) -> _Read:
    texts: list[str] = []
    excerpts: dict[str, str] = {}
    searches = 0
    usage: dict = {}
    problem = ""
    for line in ran.out.splitlines():
        line = line.strip().lstrip("﻿")
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        kind = event.get("type")
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        if kind == "item.completed" and item.get("type") == "agent_message":
            texts.append(str(item.get("text") or ""))
        elif kind == "item.completed" and item.get("type") == "web_search":
            action = item.get("action") if isinstance(item.get("action"), dict) else {}
            if action.get("type") == "search":
                searches += 1
            for result in item.get("results") or []:
                if isinstance(result, dict) and result.get("url"):
                    excerpts.setdefault(str(result["url"]), str(result.get("snippet") or ""))
        elif kind == "turn.completed" and isinstance(event.get("usage"), dict):
            usage = event["usage"]
        elif kind == "error":
            problem = str(event.get("message") or "")
        elif kind == "turn.failed":
            error = event.get("error") if isinstance(event.get("error"), dict) else {}
            problem = str(error.get("message") or problem or "the turn failed")
    if problem and not texts:
        raise ModelError(problem)
    if not texts:
        raise ModelError(_failure("it gave no answer", ran.err or ran.out))
    text = _answer(texts[-1])  # earlier messages are progress notes such as "I'll check..."
    return _Read(
        text,
        _whole(usage.get("input_tokens")),
        _whole(usage.get("output_tokens")),
        _whole(usage.get("reasoning_output_tokens")),
        searches,
        cited_links(text, excerpts),
        {"cached_input_tokens": _whole(usage.get("cached_input_tokens"))},
    )


def read_agy(ran: Ran) -> _Read:
    data = _json_object(ran.out, ran.err)
    status = data.get("status")
    if data.get("error") or (status and status != "SUCCESS"):
        raise ModelError(str(data.get("error") or f"it ended with status {status}"))
    response = data.get("response")
    if not isinstance(response, str) or not response.strip():
        denied = [
            str(d.get("action")) for d in data.get("denied_actions") or [] if isinstance(d, dict)
        ]
        if denied:
            raise ModelError(
                f"it stopped without an answer because it tried to use {', '.join(denied)}, "
                "which Conclave does not allow"
            )
    text = _answer(response)
    usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
    return _Read(
        text,
        _whole(usage.get("input_tokens")) + _whole(usage.get("cache_read_tokens")),
        _whole(usage.get("output_tokens")),
        _whole(usage.get("thinking_tokens")),
        None,  # Antigravity does not report how many searches it ran
        cited_links(text),
        {"turns": data.get("num_turns")},
    )


_READERS = {"anthropic": read_claude, "openai": read_codex, "google": read_agy}


class RoutedClient:
    """Sends each call to OpenRouter or to a command-line tool, by the seat's route."""

    def __init__(self, api, cli) -> None:
        self._api = api
        self._cli = cli

    async def complete(
        self,
        member: Member,
        messages: list[dict[str, str]],
        max_tokens: int,
        searches: int = 0,
    ) -> Completion:
        client = self._cli if member.route == "cli" else self._api
        if searches:
            return await client.complete(member, messages, max_tokens, searches)
        return await client.complete(member, messages, max_tokens)


# --- what is installed ------------------------------------------------------------------


@dataclass(frozen=True)
class ToolStatus:
    tool: Tool
    path: str | None  # None when not installed
    version: str  # first line of `--version`, or why it could not be read


def status(timeout: float = 20) -> list[ToolStatus]:
    """Each tool: whether it is installed, and its version. Asks no model anything."""
    found = []
    for tool in TOOLS.values():
        path = find(tool)
        if path is None:
            found.append(ToolStatus(tool, None, ""))
            continue
        with tempfile.TemporaryDirectory(prefix="conclave-") as workdir:
            try:
                ran = run_process([path, "--version"], "", workdir, timeout)
                lines = (ran.out or ran.err).strip().splitlines()
                version = lines[0].strip() if lines else "version not reported"
            except ModelError as error:
                version = f"could not read its version: {error}"
        found.append(ToolStatus(tool, path, version))
    return found
