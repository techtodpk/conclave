"""Conclave as an MCP server, so Claude Desktop, Cursor and other MCP clients can read
the research store and ask the council (decision 0012).

Runs over stdio: the client starts `python -m conclave mcp` and talks to it on stdin and
stdout, so nothing here may print. Every check the command line makes, from budget caps
to the monthly cap, applies to every call.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations

from conclave import __version__, library, service
from conclave.config import Config, ConfigError, default_config_path, load_config
from conclave.runner import Outcome, cap_text, dollars, evidence_of
from conclave.service import Stop
from conclave.store import DEFAULT_TOPIC, slugify

INSTRUCTIONS = """\
Conclave is the user's own research store: a council of AI models researched questions,
critiqued each other, checked key claims against web sources, and saved what they
concluded, by topic, on this machine.

- Search and read the store before answering a question it may already cover. Claims carry
  labels: [verified] means a cited web page states it; [agreed but unchecked] means members
  agreed without a source check. Open disputes are unsettled. The user's own notes outrank
  the council.
- ask_council costs the user money. A quick run (the default, about $0.01) asks one model
  with the topic's memory. Ask for full=true only when the user wants the whole council:
  it searches the web, takes one to two minutes, and costs up to the user's full-run cap.
- Add a note only when the user asks you to record something. Notes are marked as yours.
"""

READ = ToolAnnotations(read_only_hint=True, open_world_hint=False)


def create_server(config_path: Path | None = None) -> MCPServer:
    """The MCP server, reading the config at `config_path` (or the default) on every call."""
    path = (config_path or default_config_path()).expanduser()
    server = MCPServer(
        "conclave",
        title="Conclave research store",
        instructions=INSTRUCTIONS,
        version=__version__,
        website_url="https://github.com/techtodpk/conclave",
        log_level="WARNING",
    )

    def settings() -> Config:
        try:
            return load_config(path)
        except ConfigError as error:
            raise ToolError(f"Config problem: {error}") from None

    @server.tool(annotations=READ)
    def list_topics() -> str:
        """List the topics in the research store, with how many runs, claims and open
        disputes each has. Start here to see what has been researched."""
        found = library.topics(settings().store_path)
        if not found:
            return "No topics yet."
        lines = ["topic | runs | full runs | claims | open disputes | last run"]
        for t in found:
            notes = " (has the user's notes)" if t.has_notes else ""
            lines.append(
                f"{t.name} | {t.runs} | {t.full_runs} | {t.claims} | {t.open_disputes} | "
                f"{t.last_run or '-'}{notes}"
            )
        return "\n".join(lines)

    @server.tool(annotations=READ)
    def search_research(query: str, topic: str | None = None, limit: int = 10) -> str:
        """Full-text search of past research: questions, answers, one-page answers,
        summaries, disputes and the user's notes. Optionally limit to one topic."""
        slug = slugify(topic, fallback=DEFAULT_TOPIC) if topic else None
        hits = library.search(settings().store_path, query, slug, max(1, min(limit, 50)))
        if not hits:
            return "Nothing found."
        return "\n\n".join(f"{hit.path} [{hit.kind}]\n{hit.snippet}" for hit in hits)

    @server.tool(annotations=READ)
    def get_topic(topic: str) -> str:
        """What the council has concluded on a topic: every active claim with its id and
        label, the open disputes, the user's notes, and the most recent runs."""
        try:
            view = service.topic_view(settings(), topic, recent=10)
        except Stop as stop:
            raise ToolError(str(stop)) from None
        memory = view.memory
        parts = [f"# Topic: {view.slug}"]
        parts.append(
            "## The user's notes (these outrank the council)\n\n" + view.notes
            if view.notes
            else "## The user's notes\n\nNone."
        )
        claims = "\n".join(f"- {c.id}: {c.text} [{c.label}]" for c in memory.active_claims)
        parts.append(f"## Claims\n\n{claims or 'None yet.'}")
        disputes = "\n".join(f"- {d.id}: {d.text}" for d in memory.open_disputes)
        parts.append(f"## Open disputes\n\n{disputes or 'None.'}")
        runs = "\n".join(f"- {name} ({kind})" for name, kind in view.runs)
        parts.append(f"## Recent runs, newest first\n\n{runs or 'None.'}")
        return "\n\n".join(parts)

    @server.tool(annotations=READ)
    def get_run(topic: str, run: str | None = None) -> str:
        """The saved answer of one run: the one-page answer for a full run, or the
        chairman's answer for a quick run. Without `run`, the topic's most recent run.
        Run names come from get_topic."""
        try:
            view = service.topic_view(settings(), topic, recent=1)
        except Stop as stop:
            raise ToolError(str(stop)) from None
        name = run or (view.runs[0][0] if view.runs else None)
        if name is None:
            raise ToolError(f"Topic '{view.slug}' has no runs yet.")
        folder = view.folder / "runs" / name
        if "/" in name or "\\" in name or ".." in name or not folder.is_dir():
            raise ToolError(f"No run named '{name}' in topic '{view.slug}'.")
        final = folder / "final.md"
        if final.is_file():
            return final.read_text(encoding="utf-8")
        answers = sorted((folder / "answers").glob("*.md"))
        if not answers:
            raise ToolError(f"Run '{name}' has no saved answer.")
        return "\n\n---\n\n".join(a.read_text(encoding="utf-8") for a in answers)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, open_world_hint=True))
    async def ask_council(
        question: str,
        topic: str = DEFAULT_TOPIC,
        full: bool = False,
        profile: str | None = None,
    ) -> str:
        """Ask the council a question; the run is saved under the topic and reads the
        topic's memory first. Costs the user money. Quick (the default): one model answers
        with the topic's memory, about $0.01. full=true: every member searches the web,
        they review each other, key claims are checked against sources and a chairman
        writes a one-page answer; takes one to two minutes and updates the topic's memory.
        The user's budget caps apply."""
        config = settings()
        started = datetime.now().astimezone()
        try:
            plan = service.plan_ask(
                config, question, started, profile=profile, full=full, quick=not full
            )
            outcome = await service.run_plan_async(plan, config, path, question, topic, started)
        except Stop as stop:
            raise ToolError(str(stop)) from None
        return _result(outcome, config, plan.spent)

    @server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
    def add_note(topic: str, note: str, ctx: Context) -> str:
        """Add a note to a topic, only when the user asks you to record something. The
        council reads notes before every question on the topic and ranks them above its
        own conclusions. The note is marked as added by you, not the user."""
        try:
            notes, problem = service.note(settings(), topic, note, by=_client(ctx))
        except Stop as stop:
            raise ToolError(str(stop)) from None
        return f"Added to {notes}." + (f" {problem}" if problem else "")

    return server


def _client(ctx: Context | None) -> str:
    """The name the MCP client gave for itself, such as "Claude Desktop"."""
    try:
        info = ctx.session.client_params.client_info  # type: ignore[union-attr]
        name = getattr(info, "title", None) or info.name
    except Exception:  # noqa: BLE001 - outside a live session there is no client to name
        name = None
    return f"{name} via MCP" if name else "an assistant via MCP"


def _result(outcome: Outcome, settings: Config, spent: float) -> str:
    """What the assistant gets back from a run: the answer, then what it cost."""
    answered = [c for c in outcome.calls if c.stage == "research" and c.result.ok]
    if outcome.run is None:
        errors = "; ".join(f"{c.result.seat.member.model}: {c.result.error}" for c in outcome.calls)
        raise ToolError(f"No model answered, so nothing was saved. {errors}")
    if outcome.final_text:
        body = outcome.final_text
    elif outcome.mode == "quick" and answered:
        body = answered[0].result.completion.text  # type: ignore[union-attr]
    else:
        body = "No one-page answer was written. The members' answers are saved in the run."

    cap = settings.budget.cap_for(outcome.mode)
    lines = [
        "",
        "---",
        f"Conclave {outcome.mode} run on topic '{outcome.topic}', saved as "
        f"{outcome.run.path.name}.",
        f"Cost: {dollars(outcome.total_cost)} of the {cap_text(cap)} cap for "
        f"{outcome.mode} runs. This month: {dollars(spent + outcome.total_cost)} of "
        f"{cap_text(settings.budget.monthly_usd)}.",
    ]
    evidence = evidence_of(outcome)
    if evidence is not None and evidence["claims_checked"]:
        lines.append(
            f"Key claims checked against sources: {evidence['verified']} of "
            f"{evidence['claims_checked']} verified, {evidence['contradicted']} contradicted."
        )
    if outcome.changes is not None and not outcome.changes.empty:
        lines.append("The topic's memory was updated:")
        lines += outcome.changes.lines()
    lines += [f"Note: {note}" for note in outcome.notes]
    if outcome.stopped:
        lines.append(outcome.stopped)
    return body.rstrip() + "\n" + "\n".join(lines)


def serve(config_path: Path | None = None) -> None:
    """Run the server over stdio until the client disconnects."""
    create_server(config_path).run("stdio")
