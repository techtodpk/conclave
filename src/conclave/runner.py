"""One question from start to finish: checks, the stages in order, and what is saved."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from conclave import __version__
from conclave.budget import (
    cost_of,
    critique_max_tokens,
    full_run_worst_case,
    messages_tokens,
    synthesis_max_tokens,
    worst_case_cost,
)
from conclave.catalog import CatalogError, ModelInfo, closest, fetch_models
from conclave.client import OpenRouterClient
from conclave.config import Config, Member
from conclave.council import (
    Labeled,
    Review,
    Seat,
    SeatResult,
    Standing,
    ask_one,
    critique,
    critique_messages,
    final_page,
    label_answers,
    research,
    research_messages,
    standings,
    synthesis_messages,
)
from conclave.http import new_client
from conclave.store import (
    Run,
    create_run,
    write_answer,
    write_final,
    write_json,
    write_meta,
    write_question,
    write_review,
)


class Refused(Exception):
    """The run was stopped before anything was sent. The message says why."""


def dollars(amount: float) -> str:
    """A cost: small amounts get enough digits to be meaningful."""
    return f"${amount:.2f}" if amount >= 1 else f"${amount:.4f}"


def cap_text(amount: float) -> str:
    """A budget cap, as set in the config."""
    return f"${amount:.2f}"


@dataclass
class Call:
    """One model call and what it cost."""

    stage: str  # research, critique or synthesis
    result: SeatResult
    cost: float | None = None
    cost_source: str = "unknown"
    file: str | None = None
    letter: str | None = None


@dataclass
class Outcome:
    mode: str
    run: Run | None = None  # None when no model answered, so nothing was saved
    calls: list[Call] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    stopped: str | None = None
    estimate: float | None = None
    final_text: str | None = None
    table: list[Standing] = field(default_factory=list)

    @property
    def total_cost(self) -> float:
        return sum(call.cost for call in self.calls if call.cost is not None)


def check_ids(members: list[Member], catalog: dict[str, ModelInfo]) -> None:
    """Refuse the run if any model id is not in OpenRouter's list."""
    for member in dict.fromkeys(members):
        if member.model in catalog:
            continue
        near = closest(catalog, member.model)
        hint = f" Did you mean: {', '.join(near)}?" if near else ""
        raise Refused(
            f"'{member.model}' is not in OpenRouter's model list.{hint} "
            "Run `conclave models --search <text>` to look for it."
        )


async def run_question(
    question: str,
    seats: list[Seat],
    chairman: Seat | None,
    settings: Config,
    api_key: str,
    topic: str,
    mode: str,
    profile_name: str,
    started: datetime,
) -> Outcome:
    """Run the stages for one question. `chairman` is set for full runs only."""
    outcome = Outcome(mode=mode)
    cap = settings.budget.cap_for(mode)
    answer_tokens = settings.max_answer_tokens
    today = started.date()
    members = [seat.member for seat in seats]

    async with new_client() as http:
        catalog: dict[str, ModelInfo] = {}
        try:
            catalog = await fetch_models(http)
        except CatalogError as error:
            outcome.notes.append(
                f"Prices unavailable, so the cost could not be checked in advance ({error})."
            )

        research_tokens = messages_tokens(research_messages(question, today))
        if catalog:
            check_ids(members + ([chairman.member] if chairman else []), catalog)
            if chairman is None:
                estimate = worst_case_cost(members, catalog, research_tokens, answer_tokens)
            else:
                estimate = full_run_worst_case(
                    members, chairman.member, catalog, research_tokens, answer_tokens
                )
            outcome.estimate = estimate
            if estimate > cap:
                raise Refused(
                    f"This run could cost up to {dollars(estimate)}, above the {cap_text(cap)} "
                    f"cap for {mode} runs. Nothing was sent. Lower run.max_answer_tokens, "
                    "choose cheaper models, or raise the cap in the config file."
                )

        client = OpenRouterClient(http, api_key)

        # Research
        results = await research(client, seats, question, answer_tokens, today)
        if not any(result.ok for result in results):
            outcome.calls = [Call("research", result) for result in results]
            return outcome

        run = create_run(settings.store_path, topic, question, started)
        outcome.run = run
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
        answers = label_answers(results) if chairman else []
        letters = iter(a.letter for a in answers)
        for result in results:
            call = _record(Call("research", result), catalog)
            if result.completion is not None:
                letter = next(letters, None)
                path = write_answer(
                    run, result.seat.member.model, result.seat.role, result.completion.text, letter
                )
                call.file = f"answers/{path.name}"
                call.letter = letter
            outcome.calls.append(call)
        outcome.stages.append("research")

        if chairman is not None:
            await _council(
                outcome,
                client,
                run,
                catalog,
                question,
                results,
                answers,
                chairman,
                settings,
                profile_name,
                started,
                cap,
            )

    _save_meta(outcome, run, question, mode, profile_name, started, cap)
    return outcome


async def _council(
    outcome: Outcome,
    client: OpenRouterClient,
    run: Run,
    catalog: dict[str, ModelInfo],
    question: str,
    results: list[SeatResult],
    answers: list[Labeled],
    chairman: Seat,
    settings: Config,
    profile_name: str,
    started: datetime,
    cap: float,
) -> None:
    """Critique and Synthesis, each checked against the budget before it starts."""
    today = started.date()
    answer_tokens = settings.max_answer_tokens

    if len(answers) < 2:
        outcome.notes.append(
            "Only one member answered, so there was nothing to compare. "
            "Critique and the one-page answer were skipped."
        )
        return

    # Critique
    critics = [result.seat for result in results if result.ok]
    review_tokens = critique_max_tokens(answer_tokens)
    longest = max(
        messages_tokens(critique_messages(question, today, [a for a in answers if a is not own]))
        for own in answers
    )
    if _would_exceed(outcome, catalog, [s.member for s in critics], longest, review_tokens, cap):
        _stop(
            outcome, "critique", catalog, [s.member for s in critics], longest, review_tokens, cap
        )
        return

    reviews = await critique(client, answers, critics, question, review_tokens, today)
    for review in reviews:
        call = _record(Call("critique", review.result, letter=review.letter), catalog)
        if review.result.completion is not None:
            path = write_review(
                run,
                review.result.seat.member.model,
                review.letter,
                list(review.reviewed),
                review.result.completion.text,
            )
            call.file = f"critiques/{path.name}"
        outcome.calls.append(call)
    table = standings(answers, reviews)
    outcome.table = table
    write_json(run, "rankings.json", _rankings(answers, reviews, table))
    outcome.stages.append("critique")
    unreadable = sum(1 for r in reviews if r.ok and r.ranking is None)
    if unreadable:
        outcome.notes.append(
            f"{unreadable} review(s) did not give a ranking in the expected form; "
            "those rankings were left out rather than guessed."
        )

    # Synthesis
    messages = synthesis_messages(question, today, answers, reviews, table)
    page_tokens = synthesis_max_tokens(answer_tokens)
    prompt_tokens = messages_tokens(messages)
    if _would_exceed(outcome, catalog, [chairman.member], prompt_tokens, page_tokens, cap):
        _stop(outcome, "synthesis", catalog, [chairman.member], prompt_tokens, page_tokens, cap)
        return

    result = await ask_one(client, chairman, messages, page_tokens)
    outcome.calls.append(_record(Call("synthesis", result), catalog))
    if result.completion is None:
        outcome.notes.append(
            f"The chairman could not write the one-page answer ({result.error}). "
            "The answers and reviews are saved."
        )
        return

    text = final_page(
        question,
        result.completion.text,
        started.strftime("%Y-%m-%d %H:%M"),
        profile_name,
        chairman.member.model,
        table,
        reviews,
    )
    write_final(run, text)
    outcome.calls[-1].file = "final.md"
    outcome.final_text = text
    outcome.stages.append("synthesis")


def _record(call: Call, catalog: dict[str, ModelInfo]) -> Call:
    if call.result.completion is not None:
        call.cost, call.cost_source = cost_of(
            call.result.completion, catalog.get(call.result.seat.member.model)
        )
    return call


def _would_exceed(
    outcome: Outcome,
    catalog: dict[str, ModelInfo],
    members: list[Member],
    prompt_tokens: int,
    max_tokens: int,
    cap: float,
) -> bool:
    if not catalog:
        return False
    return outcome.total_cost + worst_case_cost(members, catalog, prompt_tokens, max_tokens) > cap


def _stop(
    outcome: Outcome,
    stage: str,
    catalog: dict[str, ModelInfo],
    members: list[Member],
    prompt_tokens: int,
    max_tokens: int,
    cap: float,
) -> None:
    stage_cost = worst_case_cost(members, catalog, prompt_tokens, max_tokens)
    outcome.stopped = (
        f"Stopped before the {stage} stage: it could cost up to {dollars(stage_cost)}, and this "
        f"run has already spent {dollars(outcome.total_cost)} of its {cap_text(cap)} cap. "
        "Everything up to this point is saved."
    )


def _rankings(answers: list[Labeled], reviews: list[Review], table: list[Standing]) -> dict:
    return {
        "responses": {a.letter: a.model for a in answers},
        "reviews": [
            {
                "reviewer": r.result.seat.member.model,
                "own_response": r.letter,
                "reviewed": list(r.reviewed),
                "status": "ok" if r.ok else "error",
                "ranking": list(r.ranking) if r.ranking else None,
            }
            for r in reviews
        ],
        "standings": [
            {
                "response": s.letter,
                "model": s.model,
                "average_position": s.average_position,
                "votes": s.votes,
            }
            for s in table
        ],
    }


def _save_meta(
    outcome: Outcome,
    run: Run,
    question: str,
    mode: str,
    profile_name: str,
    started: datetime,
    cap: float,
) -> None:
    calls: list[dict[str, Any]] = []
    for call in outcome.calls:
        record: dict[str, Any] = {
            "stage": call.stage,
            "model": call.result.seat.member.model,
            "route": call.result.seat.member.route,
            "role": "reviewer" if call.stage == "critique" else call.result.seat.role,
        }
        if call.letter:
            record["response"] = call.letter
        done = call.result.completion
        if done is None:
            record.update(status="error", error=call.result.error)
        else:
            record.update(
                status="ok",
                prompt_tokens=done.prompt_tokens,
                completion_tokens=done.completion_tokens,
                cost_usd=call.cost,
                cost_source=call.cost_source,
                seconds=round(done.seconds, 2),
                file=call.file,
            )
        calls.append(record)

    write_meta(
        run,
        {
            "conclave_version": __version__,
            "question": question,
            "topic": run.topic,
            "mode": mode,
            "profile": profile_name,
            "stages": outcome.stages,
            "stopped": outcome.stopped,
            "notes": outcome.notes,
            "started": started.isoformat(timespec="seconds"),
            "finished": datetime.now().astimezone().isoformat(timespec="seconds"),
            "calls": calls,
            "totals": {
                "prompt_tokens": sum(c.get("prompt_tokens", 0) for c in calls),
                "completion_tokens": sum(c.get("completion_tokens", 0) for c in calls),
                "cost_usd": round(outcome.total_cost, 6),
                "answers": sum(
                    1 for c in calls if c["stage"] == "research" and c["status"] == "ok"
                ),
                "failures": sum(1 for c in calls if c["status"] == "error"),
            },
            "budget": {
                "cap_usd": cap,
                "worst_case_estimate_usd": (
                    None if outcome.estimate is None else round(outcome.estimate, 6)
                ),
            },
        },
    )
