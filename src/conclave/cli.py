"""The `conclave` command."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer

from conclave import __version__, library
from conclave.catalog import CatalogError, ModelInfo, fetch_models, search
from conclave.config import (
    MIN_MEMBERS,
    Config,
    ConfigError,
    Member,
    default_config_path,
    default_config_text,
    load_config,
    parse_member,
)
from conclave.council import Seat
from conclave.gitstore import commit
from conclave.http import new_client
from conclave.keys import MissingKeyError, load_api_key
from conclave.memory import Changes, MemoryFileError, add_note, load_memory, read_notes
from conclave.runner import (
    Outcome,
    Refused,
    cap_text,
    check_ids,
    dollars,
    evidence_of,
    run_question,
)
from conclave.store import DEFAULT_TOPIC, init_store, month_spend, slugify

app = typer.Typer(
    help="Conclave: an LLM council that remembers.",
    no_args_is_help=True,
    add_completion=False,
)
profile_app = typer.Typer(help="Manage council profiles.", no_args_is_help=True)
app.add_typer(profile_app, name="profile")

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Config file to use. Default: ~/.conclave/config.toml"),
]

DEFAULT_STORE_LINE = 'path = "~/conclave-research"'
PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


class Stop(Exception):
    """A problem to report to the user in plain words, ending the command."""


def _fail(message: str) -> typer.Exit:
    typer.echo(message, err=True)
    return typer.Exit(code=1)


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"conclave {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Conclave: an LLM council that remembers."""


def _load(config: Path | None) -> Config:
    try:
        return load_config(config)
    except ConfigError as error:
        raise _fail(f"Config problem: {error}") from None


def _config_path(config: Path | None) -> Path:
    return (config or default_config_path()).expanduser()


def _split_ids(text: str, what: str) -> list[Member]:
    ids = [part.strip() for part in text.split(",") if part.strip()]
    try:
        return [parse_member(model_id, what) for model_id in ids]
    except ConfigError as error:
        raise Stop(str(error)) from None


# --- init and config ----------------------------------------------------------


@app.command()
def init(
    config: ConfigOption = None,
    store: Annotated[
        Path | None,
        typer.Option("--store", help="Where to keep your research. Default: ~/conclave-research"),
    ] = None,
) -> None:
    """Create the config file and the research store. Safe to run again."""
    config_path = _config_path(config)

    if config_path.exists():
        typer.echo(f"Config already exists, left unchanged: {config_path}")
    else:
        text = default_config_text()
        if store is not None:
            # as_posix keeps Windows paths valid inside a TOML string.
            text = text.replace(DEFAULT_STORE_LINE, f'path = "{store.expanduser().as_posix()}"')
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(text, encoding="utf-8")
        typer.echo(f"Created config: {config_path}")

    settings = _load(config_path)
    created = init_store(settings.store_path)
    if created:
        typer.echo(f"Created research store: {settings.store_path}")
    else:
        typer.echo(f"Research store already exists, left unchanged: {settings.store_path}")

    typer.echo("")
    typer.echo("Next: run `conclave config` to check the settings in effect.")


def _describe(member: Member) -> str:
    return f"{member.model} [{member.route}]"


@app.command("config")
def show_config(config: ConfigOption = None) -> None:
    """Show the settings in effect: store, budget caps and every profile."""
    config_path = _config_path(config)
    settings = _load(config_path)

    if config_path.is_file():
        typer.echo(f"Config file:   {config_path}")
    else:
        typer.echo(f"Config file:   none at {config_path} (using built-in defaults)")

    store_state = "exists" if settings.store_path.is_dir() else "not created yet"
    typer.echo(f"Store:         {settings.store_path} ({store_state})")
    typer.echo(f"Default run:   {settings.default_mode} mode, '{settings.default_profile}' profile")
    typer.echo(f"Longest answer: {settings.max_answer_tokens} tokens")
    typer.echo(f"Reasoning:     {settings.reasoning}")
    typer.echo(f"Claims checked per full run: {settings.claims_checked}")
    typer.echo("")
    typer.echo("Budget caps (USD)")
    typer.echo(f"  Full run:    {settings.budget.full_run_usd:.2f}")
    typer.echo(f"  Quick run:   {settings.budget.quick_run_usd:.2f}")
    typer.echo(f"  Month:       {settings.budget.monthly_usd:.2f}")

    for name in sorted(settings.profiles):
        profile = settings.profiles[name]
        marker = " (default)" if name == settings.default_profile else ""
        typer.echo("")
        typer.echo(f"Profile '{name}'{marker}")
        for member in profile.members:
            typer.echo(f"  Member:      {_describe(member)}")
        typer.echo(f"  Chairman:    {_describe(profile.chairman)}")
        typer.echo(f"  Checker:     {_describe(profile.checker)}")
        shared = profile.shared_vendors()
        if shared:
            typer.echo(
                f"  Warning: more than one member comes from {', '.join(shared)}. "
                "Models from one lab tend to share blind spots."
            )


# --- models -------------------------------------------------------------------


async def _fetch_catalog() -> dict[str, ModelInfo]:
    async with new_client() as http:
        return await fetch_models(http)


@app.command()
def models(
    search_text: Annotated[
        str | None,
        typer.Option("--search", "-s", help="Only models whose id or name contains this text."),
    ] = None,
    vendor: Annotated[
        str | None,
        typer.Option("--vendor", help="Only models from this vendor, e.g. anthropic."),
    ] = None,
    sort: Annotated[str, typer.Option("--sort", help="Sort by 'name' or 'price'.")] = "name",
    limit: Annotated[int, typer.Option("--limit", help="How many to show.", min=1)] = 30,
) -> None:
    """List available models with live prices, to help you choose a council."""
    if sort not in ("name", "price"):
        raise _fail("--sort must be 'name' or 'price'.")
    try:
        catalog = asyncio.run(_fetch_catalog())
    except CatalogError as error:
        raise _fail(f"Could not list models: {error}") from None

    found = search(catalog, text=search_text, vendor=vendor, sort=sort)
    if not found:
        typer.echo("No models match. Try a shorter search, or drop --vendor.")
        return

    shown = found[:limit]
    width = max(len(model.id) for model in shown)
    typer.echo("Prices are US dollars per million tokens, live from OpenRouter.")
    typer.echo("")
    typer.echo(f"{'Model id'.ljust(width)}  {'Input':>9}  {'Output':>9}  {'Context':>9}")
    for model in shown:
        typer.echo(
            f"{model.id.ljust(width)}  {model.prompt_per_million:>9.3f}  "
            f"{model.completion_per_million:>9.3f}  {model.context_length:>9,}"
        )
    if len(found) > len(shown):
        typer.echo("")
        typer.echo(
            f"Showing {len(shown)} of {len(found)}. Narrow it with --search or --vendor, "
            "or raise --limit."
        )


# --- profile add ----------------------------------------------------------------


def _profile_block(name: str, members: list[Member], chairman: Member, checker: Member) -> str:
    def table(member: Member) -> str:
        return f'{{ model = "{member.model}", route = "{member.route}" }}'

    lines = [f"[profiles.{name}]", "members = ["]
    lines += [f"    {table(member)}," for member in members]
    lines += ["]", f"chairman = {table(chairman)}", f"checker = {table(checker)}"]
    return "\n".join(lines) + "\n"


@profile_app.command("add")
def profile_add(
    name: Annotated[str, typer.Argument(help="A short name for the profile, e.g. mine.")],
    members: Annotated[
        str,
        typer.Option("--members", help="Comma-separated model ids for the council members."),
    ],
    chairman: Annotated[
        str, typer.Option("--chairman", help="Model id that writes the final answer.")
    ],
    checker: Annotated[
        str | None,
        typer.Option("--checker", help="Model id that verifies claims. Default: the chairman."),
    ] = None,
    no_check: Annotated[
        bool,
        typer.Option("--no-check", help="Skip checking the ids against OpenRouter's list."),
    ] = False,
    config: ConfigOption = None,
) -> None:
    """Add a council profile to your config file."""
    config_path = _config_path(config)
    try:
        if not PROFILE_NAME.match(name):
            raise Stop("A profile name uses lowercase letters, digits, '-' and '_' only.")
        if not config_path.is_file():
            raise Stop(f"No config file at {config_path}. Run `conclave init` first.")

        settings = _load(config_path)
        if name in settings.profiles:
            raise Stop(
                f"A profile named '{name}' already exists. "
                f"Pick another name, or edit it in {config_path}."
            )

        seats = _split_ids(members, "--members")
        if len(seats) < MIN_MEMBERS:
            raise Stop(f"A profile needs at least {MIN_MEMBERS} members.")
        chair = _split_ids(chairman, "--chairman")
        if len(chair) != 1:
            raise Stop("--chairman takes exactly one model id.")
        check = _split_ids(checker, "--checker") if checker else chair
        if len(check) != 1:
            raise Stop("--checker takes exactly one model id.")

        if not no_check:
            try:
                catalog = asyncio.run(_fetch_catalog())
            except CatalogError as error:
                raise Stop(
                    f"{error}. Use --no-check to add the profile without checking the ids."
                ) from None
            try:
                check_ids([*seats, chair[0], check[0]], catalog)
            except Refused as refused:
                raise Stop(str(refused)) from None
    except Stop as stop:
        raise _fail(str(stop)) from None

    original = config_path.read_text(encoding="utf-8")
    block = _profile_block(name, seats, chair[0], check[0])
    config_path.write_text(original.rstrip("\n") + "\n\n" + block, encoding="utf-8")
    try:
        profile = load_config(config_path).profile(name)
    except ConfigError as error:
        config_path.write_text(original, encoding="utf-8")
        raise _fail(f"The profile was not added, and the config is unchanged: {error}") from None

    typer.echo(f"Added profile '{name}' to {config_path}")
    shared = profile.shared_vendors()
    if shared:
        typer.echo(
            f"Warning: more than one member comes from {', '.join(shared)}. "
            "Models from one lab tend to share blind spots."
        )
    typer.echo(f'Use it with: conclave ask "your question" --profile {name} --full')


# --- ask ------------------------------------------------------------------------


@app.command()
def ask(
    question: Annotated[str, typer.Argument(help="The question to research.")],
    topic: Annotated[
        str, typer.Option("--topic", "-t", help="The topic this question belongs to.")
    ] = DEFAULT_TOPIC,
    profile: Annotated[
        str | None, typer.Option("--profile", "-p", help="Which council profile to use.")
    ] = None,
    members: Annotated[
        str | None,
        typer.Option(
            "--members", help="Comma-separated model ids to ask instead of the profile's members."
        ),
    ] = None,
    chairman: Annotated[
        str | None,
        typer.Option("--chairman", help="Model id to use as chairman instead of the profile's."),
    ] = None,
    full: Annotated[
        bool,
        typer.Option(
            "--full",
            help="Ask every member, have them review each other, then the chairman sums up.",
        ),
    ] = False,
    quick: Annotated[bool, typer.Option("--quick", help="Ask the chairman only.")] = False,
    fresh: Annotated[
        bool,
        typer.Option("--fresh", help="Ignore the topic's memory, and leave it unchanged."),
    ] = False,
    review: Annotated[
        bool,
        typer.Option("--review", help="Show the memory changes and ask before saving them."),
    ] = False,
    no_search: Annotated[
        bool,
        typer.Option(
            "--no-search",
            help="Answer from the models' training data alone: no web search, no claim checks.",
        ),
    ] = False,
    config: ConfigOption = None,
) -> None:
    """Ask the council a question and save the run to your research store."""
    config_path = _config_path(config)
    settings = _load(config_path)
    started = datetime.now().astimezone()

    try:
        if not question.strip():
            raise Stop("The question is empty.")
        if full and quick:
            raise Stop("Choose one of --full and --quick, not both.")
        if members and quick:
            raise Stop("--members asks several models, so it cannot be combined with --quick.")
        if fresh and review:
            raise Stop("--fresh leaves the memory unchanged, so there is nothing to --review.")
        mode = "full" if full or members else "quick" if quick else settings.default_mode

        try:
            chosen = settings.profile(profile)
        except ConfigError as error:
            raise Stop(str(error)) from None

        chair_member = chosen.chairman
        if chairman:
            picked = _split_ids(chairman, "--chairman")
            if len(picked) != 1:
                raise Stop("--chairman takes exactly one model id.")
            chair_member = picked[0]
        chair = Seat(chair_member, "chairman")

        if members:
            override = _split_ids(members, "--members")
            if len(override) < MIN_MEMBERS:
                raise Stop(f"--members needs at least {MIN_MEMBERS} model ids.")
            seats = [Seat(member, "member") for member in override]
        elif mode == "full":
            seats = [Seat(member, "member") for member in chosen.members]
        else:
            seats = [chair]

        for seat in [*seats, chair]:
            if seat.member.route != "api":
                raise Stop(
                    f"{seat.member.model} is set to route '{seat.member.route}'. Only route 'api' "
                    "works so far; command-line routes arrive in milestone 7."
                )

        init_store(settings.store_path)
        spent = month_spend(settings.store_path, started)
        monthly = settings.budget.monthly_usd
        if mode == "full" and spent >= monthly:
            raise Stop(
                f"This month's spending is {dollars(spent)}, at or above the {cap_text(monthly)} "
                "monthly cap, so full runs are paused. Quick runs still work. "
                "Raise budget.monthly_usd in the config file to continue."
            )

        try:
            api_key = load_api_key(config_path)
        except MissingKeyError as error:
            raise Stop(str(error)) from None

        try:
            outcome = asyncio.run(
                run_question(
                    question,
                    seats,
                    chair if mode == "full" else None,
                    settings,
                    api_key,
                    topic,
                    mode,
                    chosen.name,
                    started,
                    fresh=fresh,
                    approve=_confirm_changes if review else None,
                    checker=Seat(chosen.checker, "checker"),
                    web=settings.web_search and not no_search,
                )
            )
        except Refused as refused:
            raise Stop(str(refused)) from None
        except MemoryFileError as error:
            raise Stop(str(error)) from None
    except Stop as stop:
        raise _fail(str(stop)) from None

    _report(outcome, settings, chosen.name, outcome.topic, spent)
    if outcome.run is None:
        raise typer.Exit(code=1)


def _confirm_changes(changes: Changes) -> bool:
    typer.echo("")
    typer.echo("Proposed changes to the topic's memory:")
    for line in changes.lines():
        typer.echo(f"  {line}")
    return typer.confirm("Save these changes?", default=True)


STAGE_TITLES = {
    "research": "Research",
    "critique": "Critique",
    "verify": "Verify",
    "synthesis": "Synthesis",
    "memory": "Memory update",
}


def _report(
    outcome: Outcome, settings: Config, profile_name: str, topic: str, spent: float
) -> None:
    mode = outcome.mode
    for note in outcome.notes:
        if note.startswith("Prices unavailable"):
            typer.echo(f"Note: {note}")

    answered = [c for c in outcome.calls if c.stage == "research" and c.result.ok]
    if outcome.final_text:
        typer.echo(outcome.final_text)
        typer.echo("---")
    elif mode == "quick" and answered:
        typer.echo(answered[0].result.completion.text)  # type: ignore[union-attr]
        typer.echo("")
        typer.echo("---")

    research_calls = [c for c in outcome.calls if c.stage == "research"]
    who = "the chairman" if mode == "quick" else f"{len(research_calls)} members"
    typer.echo(f"Asked {who} (profile '{profile_name}', topic '{topic}')")
    recall = outcome.recall
    if recall is None:
        typer.echo("Memory: not used (--fresh).")
    elif not recall.text:
        typer.echo("Memory: nothing on this topic yet.")
    else:
        parts = [
            f"{recall.claims} {'claim' if recall.claims == 1 else 'claims'}",
            f"{recall.disputes} open {'dispute' if recall.disputes == 1 else 'disputes'}",
        ]
        if recall.has_notes:
            parts.append("your notes")
        typer.echo(f"Memory: recalled {', '.join(parts)}.")

    width = max(len(c.result.seat.member.model) for c in outcome.calls)
    for stage in ("research", "critique", "verify", "synthesis", "memory"):
        calls = [c for c in outcome.calls if c.stage == stage]
        if not calls:
            continue
        typer.echo("")
        if mode == "full":
            typer.echo(STAGE_TITLES[stage])
        for call in calls:
            name = call.result.seat.member.model.ljust(width)
            if call.result.completion is None:
                typer.echo(f"  {name}  FAILED  {call.result.error}")
                continue
            done = call.result.completion
            price = "cost unknown" if call.cost is None else dollars(call.cost)
            if call.cost_source == "estimated":
                price += " (estimated)"
            state = "CUT OFF" if done.cut_off else "ok"
            web = ""
            if stage == "research" and outcome.searches:
                if done.search_failed:
                    web = "  search failed, answered without it"
                elif done.searches is None:
                    web = f"  {len(done.sources)} cited"
                else:
                    count = "search" if done.searches == 1 else "searches"
                    web = f"  {done.searches} {count}, {len(done.sources)} cited"
            typer.echo(
                f"  {name}  {state}  {done.prompt_tokens:>6} in  {done.completion_tokens:>6} out  "
                f"{price}  {done.seconds:.1f}s{web}"
            )

    evidence = evidence_of(outcome)
    if evidence is not None:
        typer.echo("")
        searched = "" if evidence["searches"] is None else f"{evidence['searches']} web searches, "
        line = (
            f"Evidence: {searched}{evidence['distinct_sources']} pages cited, "
            f"{evidence['pages_fetched']} fetched for checking."
        )
        if evidence["claims_checked"]:
            line += (
                f" Key claims: {evidence['verified']} of {evidence['claims_checked']} verified, "
                f"{evidence['contradicted']} contradicted (see verification.md)."
            )
        typer.echo(line)

    for note in outcome.notes:
        if not note.startswith("Prices unavailable"):
            typer.echo("")
            typer.echo(f"Note: {note}")
    if outcome.stopped:
        typer.echo("")
        typer.echo(outcome.stopped)

    typer.echo("")
    if outcome.run is None:
        typer.echo("No model answered, so nothing was saved.")
        return

    cap = settings.budget.cap_for(mode)
    typer.echo(
        f"Cost: {dollars(outcome.total_cost)} of the {cap_text(cap)} cap for {mode} runs. "
        f"This month: {dollars(spent + outcome.total_cost)} of "
        f"{cap_text(settings.budget.monthly_usd)}."
    )
    key = outcome.key
    if key is not None and key.remaining is not None:
        left = max(key.remaining - outcome.total_cost, 0.0)
        typer.echo(
            f"OpenRouter key: about {dollars(left)} left of its {dollars(key.limit or 0)} limit."
        )
    typer.echo(f"Saved to: {outcome.run.path}")
    if outcome.final_text:
        typer.echo("The one-page answer is final.md; each answer and review is saved beside it.")
    if outcome.changes is not None and not outcome.changes.empty:
        typer.echo(f"Topic memory updated: see `conclave show {topic}`.")


# --- reading the store ------------------------------------------------------------


@app.command("topics")
def list_topics(config: ConfigOption = None) -> None:
    """List the topics in your research store."""
    settings = _load(_config_path(config))
    try:
        found = library.topics(settings.store_path)
    except MemoryFileError as error:
        raise _fail(str(error)) from None
    if not found:
        typer.echo("No topics yet. Ask a question with --topic <name> to start one.")
        return
    width = max(len(t.name) for t in found)
    header = f"{'Runs':>5}  {'Full':>5}  {'Claims':>6}  {'Disputes':>8}  Last run"
    typer.echo(f"{'Topic'.ljust(width)}  {header}")
    for t in found:
        notes = "  (notes)" if t.has_notes else ""
        typer.echo(
            f"{t.name.ljust(width)}  {t.runs:>5}  {t.full_runs:>5}  {t.claims:>6}  "
            f"{t.open_disputes:>8}  {t.last_run or '-'}{notes}"
        )


@app.command()
def show(
    topic: Annotated[str, typer.Argument(help="The topic to show.")],
    config: ConfigOption = None,
) -> None:
    """Show what the council has concluded on a topic, its open disputes and recent runs."""
    settings = _load(_config_path(config))
    slug = slugify(topic, fallback=DEFAULT_TOPIC)
    folder = settings.store_path / "topics" / slug
    if not folder.is_dir():
        raise _fail(f"No topic named '{slug}'. Run `conclave topics` to see them.")
    try:
        memory = load_memory(folder, slug)
    except MemoryFileError as error:
        raise _fail(str(error)) from None

    typer.echo(f"Topic: {slug}  ({folder})")
    typer.echo("")
    typer.echo("Claims")
    if not memory.active_claims:
        typer.echo("  None yet. Full runs on this topic add them.")
    for claim in memory.active_claims:
        typer.echo(f"  {claim.id}  {claim.text} [{claim.label}]")
    typer.echo("")
    typer.echo("Open disputes")
    if not memory.open_disputes:
        typer.echo("  None.")
    for dispute in memory.open_disputes:
        typer.echo(f"  {dispute.id}  {dispute.text}")
    notes = read_notes(folder)
    typer.echo("")
    typer.echo("Your notes" if notes else "Your notes: none. Add one with `conclave note`.")
    if notes:
        for line in notes.splitlines():
            if line.startswith("- "):
                typer.echo(f"  {line[2:]}")
    runs = sorted((folder / "runs").glob("*")) if (folder / "runs").is_dir() else []
    typer.echo("")
    typer.echo(f"Runs: {len(runs)}" + (", most recent:" if runs else ""))
    for run in runs[-5:][::-1]:
        kind = library.run_mode(run)
        if kind == "full" and not (run / "final.md").exists():
            kind = "full, stopped before the one-page answer"
        typer.echo(f"  {run.name}  ({kind})")


@app.command()
def note(
    topic: Annotated[str, typer.Argument(help="The topic the note belongs to.")],
    text: Annotated[str, typer.Argument(help="The note.")],
    config: ConfigOption = None,
) -> None:
    """Add your own note to a topic. The council reads it first, before its own conclusions."""
    if not text.strip():
        raise _fail("The note is empty.")
    settings = _load(_config_path(config))
    slug = slugify(topic, fallback=DEFAULT_TOPIC)
    folder = settings.store_path / "topics" / slug
    path = add_note(folder, slug, text, datetime.now().astimezone().date())
    problem = commit(settings.store_path, [path], f"conclave: note on {slug}")
    typer.echo(f"Added to {path}")
    if problem:
        typer.echo(problem)


@app.command("search")
def search_store(
    query: Annotated[str, typer.Argument(help="Words to look for.")],
    topic: Annotated[
        str | None, typer.Option("--topic", "-t", help="Only search this topic.")
    ] = None,
    limit: Annotated[int, typer.Option("--limit", help="How many results.", min=1)] = 10,
    config: ConfigOption = None,
) -> None:
    """Search your past research: final answers, questions, answers, summaries and notes."""
    settings = _load(_config_path(config))
    slug = slugify(topic, fallback=DEFAULT_TOPIC) if topic else None
    hits = library.search(settings.store_path, query, slug, limit)
    if not hits:
        typer.echo("Nothing found.")
        return
    for hit in hits:
        typer.echo(f"{hit.path}  [{hit.kind}]")
        typer.echo(f"  {hit.snippet}")


@app.command()
def leaderboard(
    topic: Annotated[
        str | None, typer.Option("--topic", "-t", help="Only count runs on this topic.")
    ] = None,
    config: ConfigOption = None,
) -> None:
    """Which models the others ranked highest across your own full runs."""
    settings = _load(_config_path(config))
    slug = slugify(topic, fallback=DEFAULT_TOPIC) if topic else None
    table = library.leaderboard(settings.store_path, slug)
    if not table:
        typer.echo("No rankings yet. Full runs (--full) record how members rank each other.")
        return
    width = max(len(p.model) for p in table)
    typer.echo("Score: 0 means always ranked best, 1 always ranked worst.")
    typer.echo("")
    typer.echo(f"{'Model'.ljust(width)}  {'Score':>5}  {'Firsts':>6}  {'Rankings':>8}  {'Runs':>4}")
    for p in table:
        typer.echo(
            f"{p.model.ljust(width)}  {p.score:>5.2f}  {p.firsts:>6}  {p.rankings:>8}  {p.runs:>4}"
        )
    typer.echo("")
    typer.echo("Few runs make for a noisy ranking. Treat this as a hint, not a verdict.")


if __name__ == "__main__":
    app()
