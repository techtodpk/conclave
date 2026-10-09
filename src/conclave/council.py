"""The council's stages: Research, Critique and Synthesis."""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, replace
from datetime import date
from importlib import resources
from typing import Protocol

from conclave.client import Completion, ModelError
from conclave.config import Member

LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


class ModelClient(Protocol):
    async def complete(
        self,
        member: Member,
        messages: list[dict[str, str]],
        max_tokens: int,
        searches: int = 0,
    ) -> Completion: ...


@dataclass(frozen=True)
class Seat:
    """A model and the part it plays in this run."""

    member: Member
    role: str  # "member" or "chairman"


@dataclass(frozen=True)
class SeatResult:
    seat: Seat
    completion: Completion | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.completion is not None


@dataclass(frozen=True)
class Labeled:
    """An answer under its hidden name."""

    letter: str
    model: str
    text: str


@dataclass(frozen=True)
class Review:
    """One member's critique of the other answers."""

    result: SeatResult
    letter: str  # the reviewer's own answer, which it did not see
    reviewed: tuple[str, ...]
    ranking: tuple[str, ...] | None  # None when the ranking could not be read

    @property
    def ok(self) -> bool:
        return self.result.ok


@dataclass(frozen=True)
class Standing:
    letter: str
    model: str
    average_position: float | None
    votes: int


def load_prompt(name: str) -> str:
    """Read a stage prompt that ships with the package."""
    prompt = resources.files("conclave").joinpath("prompts", f"{name}.md")
    return prompt.read_text(encoding="utf-8").strip()


def _header(question: str, today: date, recall: str = "") -> str:
    head = f"Today's date: {today.isoformat()}\n\n"
    if recall:
        head += (
            "## Earlier research on this topic\n\n"
            "Earlier runs of this council reached the conclusions below. Treat them as prior "
            "findings, not established facts: build on them, and say plainly where your answer "
            "confirms, corrects or contradicts one, citing its id (C1, D1). The user's notes "
            "take precedence over earlier conclusions.\n\n"
            f"{recall}\n\n## The question\n\n"
        )
    return head + f"Question: {question}"


def _responses(answers: list[Labeled]) -> str:
    return "\n\n".join(f"### Response {a.letter}\n\n{a.text}" for a in answers)


async def ask_one(
    client: ModelClient,
    seat: Seat,
    messages: list[dict[str, str]],
    max_tokens: int,
    searches: int = 0,
) -> SeatResult:
    """Make one call. Errors are returned, never raised, so one failure stops nothing else."""
    try:
        if searches:
            completion = await client.complete(seat.member, messages, max_tokens, searches)
        else:
            completion = await client.complete(seat.member, messages, max_tokens)
    except ModelError as error:
        return SeatResult(seat=seat, error=str(error))
    except Exception as error:  # noqa: BLE001 - keep the other calls' results
        return SeatResult(seat=seat, error=f"unexpected {type(error).__name__}: {error}")
    return SeatResult(seat=seat, completion=completion)


# --- Research -------------------------------------------------------------------


def research_prompt(web: bool) -> str:
    """The Research stage's instructions, with or without web search."""
    rule = load_prompt("research_web" if web else "research_offline")
    tail = (
        ", then the links it rests on, if any, as in: Sources: [Python docs](https://docs.python.org/3/)."
        if web
        else "."
    )
    return load_prompt("research").replace("{sources_rule}", rule).replace("{claim_sources}", tail)


def research_messages(
    question: str, today: date, recall: str = "", web: bool = False
) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": research_prompt(web)},
        {"role": "user", "content": _header(question, today, recall)},
    ]


async def research(
    client: ModelClient,
    seats: list[Seat],
    question: str,
    max_tokens: int,
    today: date,
    recall: str = "",
    searches: int = 0,
) -> list[SeatResult]:
    """Ask every seat the question at the same time. `searches` above 0 allows web search."""
    messages = research_messages(question, today, recall, web=searches > 0)
    return list(
        await asyncio.gather(
            *(_research_one(client, s, messages, max_tokens, searches) for s in seats)
        )
    )


SEARCH_NUDGE = (
    "\n\nYou have not searched yet. Search the web before you answer: look up the facts your "
    "answer depends on most, and cite the pages you use. Your key claims will be checked "
    "against those pages, and a claim with no source cannot be checked."
)


def _unsourced(completion: Completion) -> bool:
    """An answer given without searching or citing anything, when search worked."""
    return not completion.sources and not completion.searches and completion.search_failed is None


async def _research_one(
    client: ModelClient,
    seat: Seat,
    messages: list[dict[str, str]],
    max_tokens: int,
    searches: int,
) -> SeatResult:
    """One member's answer. If it searched nothing and cited nothing, ask once more to search.

    The second answer replaces the first, and both are paid for. If the second call fails,
    the first answer stands.
    """
    first = await ask_one(client, seat, messages, max_tokens, searches)
    if not searches or first.completion is None or not _unsourced(first.completion):
        return first
    nudged = [*messages[:-1], {**messages[-1], "content": messages[-1]["content"] + SEARCH_NUDGE}]
    second = await ask_one(client, seat, nudged, max_tokens, searches)
    if second.completion is None:
        return first
    before, after = first.completion.cost_usd, second.completion.cost_usd
    cost = None if before is None or after is None else before + after
    return SeatResult(
        seat=seat,
        completion=replace(second.completion, cost_usd=cost, asked_to_search=True),
    )


CUT_OFF_NOTE = "\n\n[This text was cut off at the length limit, so it ends early.]"


def shown_text(completion: Completion) -> str:
    """What other models are shown: the text, marked if it was cut off at the length limit."""
    return completion.text + (CUT_OFF_NOTE if completion.cut_off else "")


def label_answers(results: list[SeatResult]) -> list[Labeled]:
    """Give each successful answer a hidden name, in seat order."""
    answered = [r for r in results if r.completion is not None]
    return [
        Labeled(letter, r.seat.member.model, shown_text(r.completion))  # type: ignore[arg-type]
        for letter, r in zip(LETTERS, answered, strict=False)
    ]


# --- Critique -------------------------------------------------------------------


def critique_messages(question: str, today: date, others: list[Labeled]) -> list[dict[str, str]]:
    names = ", ".join(f"Response {a.letter}" for a in others)
    user = (
        f"{_header(question, today)}\n\n"
        f"Here are {len(others)} answers to review: {names}.\n\n"
        f"{_responses(others)}"
    )
    return [
        {"role": "system", "content": load_prompt("critique")},
        {"role": "user", "content": user},
    ]


_RANKING_HEADING = re.compile(r"^#+\s*ranking\b.*$", re.IGNORECASE | re.MULTILINE)
_RANKED = re.compile(r"response\s+([A-Z])\b", re.IGNORECASE)


def parse_ranking(text: str, expected: list[str]) -> tuple[str, ...] | None:
    """Read the ranking from the last 'Ranking' section.

    Returns the letters best first, or None unless every expected letter appears
    exactly once. A loose ranking is recorded as unreadable rather than guessed.
    """
    headings = list(_RANKING_HEADING.finditer(text))
    if not headings:
        return None
    section = text[headings[-1].end() :]
    found = [match.group(1).upper() for match in _RANKED.finditer(section)]
    if sorted(found) != sorted(expected) or len(set(found)) != len(found):
        return None
    return tuple(found)


async def critique(
    client: ModelClient,
    answers: list[Labeled],
    critics: list[Seat],
    question: str,
    max_tokens: int,
    today: date,
) -> list[Review]:
    """Every member who answered reviews every other answer, at the same time.

    `critics` is in the same order as `answers`: critic i wrote answer i.
    """

    async def review(seat: Seat, own: Labeled) -> Review:
        others = [a for a in answers if a.letter != own.letter]
        result = await ask_one(client, seat, critique_messages(question, today, others), max_tokens)
        expected = [a.letter for a in others]
        ranking = parse_ranking(result.completion.text, expected) if result.completion else None
        return Review(result=result, letter=own.letter, reviewed=tuple(expected), ranking=ranking)

    return list(
        await asyncio.gather(
            *(review(seat, own) for seat, own in zip(critics, answers, strict=True))
        )
    )


def standings(answers: list[Labeled], reviews: list[Review]) -> list[Standing]:
    """Average position of each answer across the readable rankings, best first."""
    positions: dict[str, list[int]] = {a.letter: [] for a in answers}
    for review in reviews:
        if review.ranking is None:
            continue
        for place, letter in enumerate(review.ranking, start=1):
            positions[letter].append(place)

    table = [
        Standing(
            letter=a.letter,
            model=a.model,
            average_position=(
                round(sum(positions[a.letter]) / len(positions[a.letter]), 2)
                if positions[a.letter]
                else None
            ),
            votes=len(positions[a.letter]),
        )
        for a in answers
    ]
    return sorted(
        table,
        key=lambda s: (s.average_position is None, s.average_position or 0.0, s.letter),
    )


# --- Synthesis ------------------------------------------------------------------


def synthesis_messages(
    question: str,
    today: date,
    answers: list[Labeled],
    reviews: list[Review],
    table: list[Standing],
    recall: str = "",
    checks: str = "",
) -> list[dict[str, str]]:
    readable = [r for r in reviews if r.ok]
    review_text = "\n\n".join(
        f"### Review by the author of Response {r.letter}\n\n{shown_text(r.result.completion)}"  # type: ignore[arg-type]
        for r in readable
    )
    ranked = [s for s in table if s.average_position is not None]
    ranking_line = (
        ", ".join(f"Response {s.letter} {s.average_position}" for s in ranked)
        if ranked
        else "No readable rankings."
    )
    user = (
        f"{_header(question, today, recall)}\n\n"
        f"## The members' answers\n\n{_responses(answers)}\n\n"
        f"## The members' reviews of each other\n\n{review_text or 'No reviews were returned.'}\n\n"
        f"## Peer ranking\n\nAverage position, lower is better: {ranking_line}"
    )
    if checks:
        user += (
            "\n\n## Claim checks\n\nA checker tested these claims against the pages the members "
            "cited. Use the label shown for each one that appears among your key claims.\n\n"
            + checks
        )
    return [
        {"role": "system", "content": load_prompt("synthesis")},
        {"role": "user", "content": user},
    ]


def final_page(
    question: str,
    body: str,
    asked: str,
    profile: str,
    chairman: str,
    table: list[Standing],
    reviews: list[Review],
    evidence: str = "",
    sources: str = "",
    checked: bool = False,
) -> str:
    """The one-page answer saved as final.md: the chairman's text plus how it was made.

    `evidence` replaces the line under the title that says what was checked; `sources`
    is the list of pages the members cited, added after the chairman's text.
    """
    readable = sum(1 for r in reviews if r.ranking is not None)
    rows = "\n".join(
        f"| {s.letter} | `{s.model}` | "
        + (
            f"{s.average_position} ({s.votes} {'review' if s.votes == 1 else 'reviews'})"
            if s.average_position is not None
            else "not ranked"
        )
        + " |"
        for s in table
    )
    evidence = evidence or (
        "Nothing here was checked against live sources; claims come from the models' training data."
    )
    made = (
        "Each member answered alone, then reviewed the others' answers with the authors hidden "
        f"behind letters. The chairman, `{chairman}`, wrote this page from the answers and "
        "reviews"
    )
    made += ", and from the claim checks in verification.md.\n\n" if checked else ".\n\n"
    return (
        f"# {question.strip()}\n\n"
        f"*Conclave full run, {asked}, profile '{profile}'. {evidence}*\n\n"
        f"{body.strip()}\n\n"
        + (f"## Sources\n\n{sources.strip()}\n\n" if sources else "")
        + "## How this answer was made\n\n"
        + made
        + "| Response | Model | Peer ranking (average position, lower is better) |\n"
        "| --- | --- | --- |\n"
        f"{rows}\n\n"
        f"Readable rankings: {readable} of {len(reviews)}.\n"
    )


# --- Memory update ----------------------------------------------------------------


def memory_messages(topic: str, listing: str, answer: str, today: date) -> list[dict[str, str]]:
    user = (
        f"Today's date: {today.isoformat()}\n\nTopic: {topic}\n\n{listing}\n\n"
        f"## The new run's final answer\n\n{answer}"
    )
    return [
        {"role": "system", "content": load_prompt("memory")},
        {"role": "user", "content": user},
    ]
