"""The `conclave` command."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated, Any

import typer

from conclave import __version__
from conclave.budget import cost_of, worst_case_cost
from conclave.catalog import CatalogError, ModelInfo, closest, fetch_models, search
from conclave.client import OpenRouterClient
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
from conclave.council import Seat, SeatResult, research, research_messages
from conclave.http import new_client
from conclave.keys import MissingKeyError, load_api_key
from conclave.store import (
    DEFAULT_TOPIC,
    Run,
    create_run,
    init_store,
    month_spend,
    slugify,
    write_answer,
    write_meta,
    write_question,
)

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


def _dollars(amount: float) -> str:
    """A cost: small amounts get enough digits to be meaningful."""
    return f"${amount:.2f}" if amount >= 1 else f"${amount:.4f}"


def _cap(amount: float) -> str:
    """A budget cap, as set in the config."""
    return f"${amount:.2f}"


def _split_ids(text: str, what: str) -> list[Member]:
    ids = [part.strip() for part in text.split(",") if part.strip()]
    try:
        return [parse_member(model_id, what) for model_id in ids]
    except ConfigError as error:
        raise Stop(str(error)) from None


def _check_ids(members: list[Member], catalog: dict[str, ModelInfo]) -> None:
    """Stop with suggestions if any model id is not in OpenRouter's list."""
    for member in dict.fromkeys(members):
        if member.model in catalog:
            continue
        near = closest(catalog, member.model)
        hint = f" Did you mean: {', '.join(near)}?" if near else ""
        raise Stop(
            f"'{member.model}' is not in OpenRouter's model list.{hint} "
            "Run `conclave models --search <text>` to look for it."
        )


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
            _check_ids([*seats, chair[0], check[0]], catalog)
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


@dataclass
class AskResult:
    run: Run | None  # None when no model answered, so nothing was saved
    results: list[SeatResult]
    costs: list[tuple[float | None, str]]
    total_cost: float
    estimate: float | None
    notes: list[str] = field(default_factory=list)


async def _ask(
    question: str,
    seats: list[Seat],
    settings: Config,
    api_key: str,
    topic: str,
    mode: str,
    profile_name: str,
    started: datetime,
) -> AskResult:
    cap = settings.budget.cap_for(mode)
    notes: list[str] = []
    members = [seat.member for seat in seats]

    async with new_client() as http:
        catalog: dict[str, ModelInfo] = {}
        try:
            catalog = await fetch_models(http)
        except CatalogError as error:
            notes.append(f"Prices unavailable, so the cost could not be estimated ({error}).")

        estimate: float | None = None
        if catalog:
            _check_ids(members, catalog)
            prompt_text = "\n".join(
                m["content"] for m in research_messages(question, started.date())
            )
            estimate = worst_case_cost(members, catalog, prompt_text, settings.max_answer_tokens)
            if estimate > cap:
                raise Stop(
                    f"This run could cost up to {_dollars(estimate)}, above the {_cap(cap)} "
                    f"cap for {mode} runs. Nothing was sent. Lower run.max_answer_tokens, "
                    f"choose cheaper models, or raise the cap in the config file."
                )

        client = OpenRouterClient(http, api_key)
        results = await research(
            client, seats, question, settings.max_answer_tokens, started.date()
        )

    if not any(result.ok for result in results):
        # Nothing worth keeping: the store holds research, not failed attempts.
        return AskResult(
            run=None,
            results=results,
            costs=[(None, "unknown")] * len(results),
            total_cost=0.0,
            estimate=estimate,
            notes=notes,
        )

    run = create_run(settings.store_path, topic, question, started)
    write_question(
        run,
        question,
        {
            "Asked": started.isoformat(timespec="seconds"),
            "Topic": run.topic,
            "Mode": mode,
            "Profile": profile_name,
        },
    )

    costs: list[tuple[float | None, str]] = []
    records: list[dict[str, Any]] = []
    for result in results:
        record: dict[str, Any] = {
            "model": result.seat.member.model,
            "route": result.seat.member.route,
            "role": result.seat.role,
        }
        if result.completion is None:
            costs.append((None, "unknown"))
            record.update(status="error", error=result.error)
        else:
            cost, source = cost_of(result.completion, catalog.get(result.seat.member.model))
            costs.append((cost, source))
            answer = write_answer(
                run, result.seat.member.model, result.seat.role, result.completion.text
            )
            record.update(
                status="ok",
                prompt_tokens=result.completion.prompt_tokens,
                completion_tokens=result.completion.completion_tokens,
                cost_usd=cost,
                cost_source=source,
                seconds=round(result.completion.seconds, 2),
                answer_file=f"answers/{answer.name}",
            )
        records.append(record)

    total_cost = sum(cost for cost, _ in costs if cost is not None)
    finished = datetime.now().astimezone()
    write_meta(
        run,
        {
            "conclave_version": __version__,
            "question": question,
            "topic": run.topic,
            "mode": mode,
            "profile": profile_name,
            "stages": ["research"],
            "started": started.isoformat(timespec="seconds"),
            "finished": finished.isoformat(timespec="seconds"),
            "seats": records,
            "totals": {
                "prompt_tokens": sum(r.get("prompt_tokens", 0) for r in records),
                "completion_tokens": sum(r.get("completion_tokens", 0) for r in records),
                "cost_usd": round(total_cost, 6),
                "answers": sum(1 for r in records if r["status"] == "ok"),
                "failures": sum(1 for r in records if r["status"] == "error"),
            },
            "budget": {
                "cap_usd": cap,
                "worst_case_estimate_usd": None if estimate is None else round(estimate, 6),
            },
        },
    )
    return AskResult(
        run=run, results=results, costs=costs, total_cost=total_cost, estimate=estimate, notes=notes
    )


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
    full: Annotated[bool, typer.Option("--full", help="Ask every council member.")] = False,
    quick: Annotated[bool, typer.Option("--quick", help="Ask the chairman only.")] = False,
    config: ConfigOption = None,
) -> None:
    """Ask the council a question and save every answer to your research store."""
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
        mode = "full" if full or members else "quick" if quick else settings.default_mode

        try:
            chosen = settings.profile(profile)
        except ConfigError as error:
            raise Stop(str(error)) from None

        if members:
            override = _split_ids(members, "--members")
            if len(override) < MIN_MEMBERS:
                raise Stop(f"--members needs at least {MIN_MEMBERS} model ids.")
            seats = [Seat(member, "member") for member in override]
        elif mode == "full":
            seats = [Seat(member, "member") for member in chosen.members]
        else:
            seats = [Seat(chosen.chairman, "chairman")]

        for seat in seats:
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
                f"This month's spending is {_dollars(spent)}, at or above the {_cap(monthly)} "
                "monthly cap, so full runs are paused. Quick runs still work. "
                "Raise budget.monthly_usd in the config file to continue."
            )

        try:
            api_key = load_api_key(config_path)
        except MissingKeyError as error:
            raise Stop(str(error)) from None

        outcome = asyncio.run(
            _ask(question, seats, settings, api_key, topic, mode, chosen.name, started)
        )
    except Stop as stop:
        raise _fail(str(stop)) from None

    _report(outcome, settings, mode, chosen.name, slugify(topic, fallback=DEFAULT_TOPIC), spent)
    if not any(result.ok for result in outcome.results):
        raise typer.Exit(code=1)


def _report(
    outcome: AskResult, settings: Config, mode: str, profile_name: str, topic: str, spent: float
) -> None:
    for note in outcome.notes:
        typer.echo(f"Note: {note}")

    answered = [r for r in outcome.results if r.ok]
    if mode == "quick" and answered:
        typer.echo(answered[0].completion.text)  # type: ignore[union-attr]
        typer.echo("")
        typer.echo("---")

    who = "the chairman" if mode == "quick" else f"{len(outcome.results)} members"
    typer.echo(f"Asked {who} (profile '{profile_name}', topic '{topic}')")
    typer.echo("")

    width = max(len(r.seat.member.model) for r in outcome.results)
    for result, (cost, source) in zip(outcome.results, outcome.costs, strict=True):
        name = result.seat.member.model.ljust(width)
        if result.completion is None:
            typer.echo(f"  {name}  FAILED  {result.error}")
            continue
        done = result.completion
        price = "cost unknown" if cost is None else _dollars(cost)
        if source == "estimated":
            price += " (estimated)"
        typer.echo(
            f"  {name}  ok  {done.prompt_tokens:>6} in  {done.completion_tokens:>6} out  "
            f"{price}  {done.seconds:.1f}s"
        )

    typer.echo("")
    if outcome.run is None:
        typer.echo("No model answered, so nothing was saved.")
        return

    cap = settings.budget.cap_for(mode)
    typer.echo(
        f"Cost: {_dollars(outcome.total_cost)} of the {_cap(cap)} cap for {mode} runs. "
        f"This month: {_dollars(spent + outcome.total_cost)} of "
        f"{_cap(settings.budget.monthly_usd)}."
    )
    typer.echo(f"Saved to: {outcome.run.path}")
    if mode == "full":
        typer.echo(
            "Each answer is in the 'answers' folder. Cross-critique and the one-page "
            "synthesis arrive in milestone 3."
        )


if __name__ == "__main__":
    app()
