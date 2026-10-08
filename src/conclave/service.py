"""What the command line and the MCP server share: planning and running a question,
and reading a topic. Each check lives here once, so both front ends refuse the same things.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from conclave import library
from conclave.config import MIN_MEMBERS, Config, ConfigError, Member, Profile, parse_member
from conclave.council import Seat
from conclave.gitstore import commit
from conclave.keys import MissingKeyError, load_api_key
from conclave.memory import (
    MemoryFileError,
    TopicMemory,
    add_note,
    load_memory,
    read_notes,
)
from conclave.runner import Outcome, Refused, cap_text, dollars, run_question
from conclave.store import DEFAULT_TOPIC, init_store, month_spend, slugify


class Stop(Exception):
    """A problem to report in plain words. Nothing was sent when this is raised."""


def split_ids(text: str, what: str) -> list[Member]:
    ids = [part.strip() for part in text.split(",") if part.strip()]
    try:
        return [parse_member(model_id, what) for model_id in ids]
    except ConfigError as error:
        raise Stop(str(error)) from None


@dataclass(frozen=True)
class Plan:
    """Who a run will ask, decided before anything is sent."""

    mode: str  # "quick" or "full"
    profile: Profile
    seats: list[Seat]
    chairman: Seat
    spent: float  # this month's recorded spending before the run


def plan_ask(
    settings: Config,
    question: str,
    started: datetime,
    *,
    profile: str | None = None,
    members: str | None = None,
    chairman: str | None = None,
    full: bool = False,
    quick: bool = False,
    fresh: bool = False,
    review: bool = False,
) -> Plan:
    """Check a request and decide its mode and seats. Raises Stop with the reason if not."""
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
        picked = split_ids(chairman, "--chairman")
        if len(picked) != 1:
            raise Stop("--chairman takes exactly one model id.")
        chair_member = picked[0]
    chair = Seat(chair_member, "chairman")

    if members:
        override = split_ids(members, "--members")
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
                "works so far; command-line routes arrive in milestone 8."
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
    return Plan(mode, chosen, seats, chair, spent)


async def run_plan_async(
    plan: Plan,
    settings: Config,
    config_path: Path,
    question: str,
    topic: str,
    started: datetime,
    *,
    fresh: bool = False,
    search: bool = True,
    approve=None,
    progress=None,
) -> Outcome:
    """Load the key and run the question. Raises Stop for anything refused before sending."""
    try:
        api_key = load_api_key(config_path)
    except MissingKeyError as error:
        raise Stop(str(error)) from None
    try:
        return await run_question(
            question,
            plan.seats,
            plan.chairman if plan.mode == "full" else None,
            settings,
            api_key,
            topic,
            plan.mode,
            plan.profile.name,
            started,
            fresh=fresh,
            approve=approve,
            checker=Seat(plan.profile.checker, "checker"),
            web=settings.web_search and search,
            progress=progress,
        )
    except Refused as refused:
        raise Stop(str(refused)) from None
    except MemoryFileError as error:
        raise Stop(str(error)) from None


def run_plan(*args, **kwargs) -> Outcome:
    """run_plan_async for callers outside an event loop, such as the command line."""
    return asyncio.run(run_plan_async(*args, **kwargs))


# --- reading and writing a topic ---------------------------------------------------


@dataclass(frozen=True)
class TopicView:
    slug: str
    folder: Path
    memory: TopicMemory
    notes: str
    runs: list[tuple[str, str]]  # (run folder name, kind), most recent first


def topic_view(settings: Config, topic: str, recent: int = 5) -> TopicView:
    """A topic's memory, notes and recent runs. Raises Stop if there is no such topic."""
    slug = slugify(topic, fallback=DEFAULT_TOPIC)
    folder = settings.store_path / "topics" / slug
    if not folder.is_dir():
        raise Stop(f"No topic named '{slug}'. Run `conclave topics` to see them.")
    try:
        memory = load_memory(folder, slug)
    except MemoryFileError as error:
        raise Stop(str(error)) from None
    runs = sorted((folder / "runs").glob("*")) if (folder / "runs").is_dir() else []
    shown = []
    for run in runs[-recent:][::-1]:
        kind = library.run_mode(run)
        if kind == "full" and not (run / "final.md").exists():
            kind = "full, stopped before the one-page answer"
        shown.append((run.name, kind))
    return TopicView(slug, folder, memory, read_notes(folder), shown)


def note(settings: Config, topic: str, text: str, by: str | None = None) -> tuple[Path, str | None]:
    """Append a note to a topic. `by` marks a note added by an assistant rather than the user.

    Returns the notes file and, if the store is a Git repository and the commit failed, why.
    """
    if not text.strip():
        raise Stop("The note is empty.")
    slug = slugify(topic, fallback=DEFAULT_TOPIC)
    folder = settings.store_path / "topics" / slug
    body = " ".join(text.split())
    if by:
        body += f" (added by {by})"
    path = add_note(folder, slug, body, datetime.now().astimezone().date())
    return path, commit(settings.store_path, [path], f"conclave: note on {slug}")
