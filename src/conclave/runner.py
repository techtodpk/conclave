"""One question from start to finish: checks, the stages in order, and what is saved."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from conclave import __version__
from conclave.budget import (
    MEMORY_MAX_TOKENS,
    cost_of,
    critique_max_tokens,
    estimate_tokens,
    full_run_worst_case,
    messages_tokens,
    synthesis_max_tokens,
    worst_case_cost,
)
from conclave.catalog import CatalogError, ModelInfo, closest, fetch_models
from conclave.client import KeyStatus, OpenRouterClient, key_status
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
    memory_messages,
    research,
    research_messages,
    standings,
    synthesis_messages,
)
from conclave.gitstore import commit
from conclave.http import new_client
from conclave.memory import (
    Changes,
    Recall,
    TopicMemory,
    apply_patch,
    build_recall,
    load_memory,
    memory_listing,
    parse_patch,
    save_memory,
)
from conclave.store import (
    DEFAULT_TOPIC,
    Run,
    create_run,
    slugify,
    write_answer,
    write_final,
    write_json,
    write_meta,
    write_question,
    write_review,
)

# Asked before memory changes are saved, when the user wants to approve them.
Approve = Callable[[Changes], bool]


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

    stage: str  # research, critique, synthesis or memory
    result: SeatResult
    cost: float | None = None
    cost_source: str = "unknown"
    file: str | None = None
    letter: str | None = None


@dataclass
class Outcome:
    mode: str
    topic: str
    run: Run | None = None  # None when no model answered, so nothing was saved
    calls: list[Call] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    stages: list[str] = field(default_factory=list)
    stopped: str | None = None
    estimate: float | None = None
    final_text: str | None = None
    table: list[Standing] = field(default_factory=list)
    recall: Recall | None = None
    changes: Changes | None = None
    key: KeyStatus | None = None

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


@dataclass
class _Context:
    """What every stage of one run needs."""

    question: str
    settings: Config
    started: datetime
    profile_name: str
    cap: float
    catalog: dict[str, ModelInfo]
    topic_dir: Path
    memory: TopicMemory | None  # None when the run neither reads nor writes memory
    recall_text: str


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
    fresh: bool = False,
    approve: Approve | None = None,
) -> Outcome:
    """Run the stages for one question. `chairman` is set for full runs only.

    `fresh` skips the topic's memory entirely. `approve`, when given, is asked before
    memory changes are saved.
    """
    topic_slug = slugify(topic, fallback=DEFAULT_TOPIC)
    outcome = Outcome(mode=mode, topic=topic_slug)
    cap = settings.budget.cap_for(mode)
    answer_tokens = settings.max_answer_tokens
    today = started.date()
    members = [seat.member for seat in seats]
    topic_dir = settings.store_path / "topics" / topic_slug

    memory = None if fresh else load_memory(topic_dir, topic_slug)
    recall_text = ""
    if memory is not None:
        outcome.recall = build_recall(topic_dir, memory)
        recall_text = outcome.recall.text
        if outcome.recall.truncated:
            outcome.notes.append("The topic's memory was long, so the recall was cut short.")

    async with new_client() as http:
        catalog: dict[str, ModelInfo] = {}
        try:
            catalog = await fetch_models(http)
        except CatalogError as error:
            outcome.notes.append(
                f"Prices unavailable, so the cost could not be checked in advance ({error})."
            )

        research_tokens = messages_tokens(research_messages(question, today, recall_text))
        if catalog:
            check_ids(members + ([chairman.member] if chairman else []), catalog)
            if chairman is None:
                estimate = worst_case_cost(members, catalog, research_tokens, answer_tokens)
            else:
                listing = None if memory is None else estimate_tokens(memory_listing(memory))
                estimate = full_run_worst_case(
                    members, chairman.member, catalog, research_tokens, answer_tokens, listing
                )
            outcome.estimate = estimate
            if estimate > cap:
                raise Refused(
                    f"This run could cost up to {dollars(estimate)}, above the {cap_text(cap)} "
                    f"cap for {mode} runs. Nothing was sent. Lower run.max_answer_tokens, "
                    "choose cheaper models, or raise the cap in the config file."
                )

        outcome.key = await key_status(http, api_key)
        remaining = outcome.key.remaining if outcome.key else None
        if remaining is not None and outcome.estimate is not None and outcome.estimate > remaining:
            raise Refused(
                f"Your OpenRouter key has {dollars(remaining)} left of its spending limit, and "
                f"this run could cost up to {dollars(outcome.estimate)}. Nothing was sent. Add "
                "credit or raise the key's limit at https://openrouter.ai/keys, or try a quick "
                "run or cheaper models."
            )

        client = OpenRouterClient(http, api_key, reasoning=settings.reasoning)
        context = _Context(
            question, settings, started, profile_name, cap, catalog, topic_dir, memory, recall_text
        )

        # Research
        results = await research(client, seats, question, answer_tokens, today, recall_text)
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
                "Memory": "not used (--fresh)"
                if fresh
                else "read" + (" and updated" if chairman else ""),
            },
        )
        if recall_text:
            (run.path / "recall.md").write_text(
                "# Earlier research given to the council\n\n" + recall_text + "\n",
                encoding="utf-8",
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
            body = await _council(outcome, client, run, context, results, answers, chairman)
            if body is not None and memory is not None:
                await _update_memory(outcome, client, run, context, chairman, body, approve)

    _save_meta(outcome, run, question, mode, profile_name, started, cap)
    _commit(outcome, settings.store_path, run, topic_dir, question)
    return outcome


async def _council(
    outcome: Outcome,
    client: OpenRouterClient,
    run: Run,
    context: _Context,
    results: list[SeatResult],
    answers: list[Labeled],
    chairman: Seat,
) -> str | None:
    """Critique and Synthesis. Returns the chairman's text, or None if there is no page."""
    today = context.started.date()
    answer_tokens = context.settings.max_answer_tokens
    catalog, cap, question = context.catalog, context.cap, context.question

    if len(answers) < 2:
        outcome.notes.append(
            "Only one member answered, so there was nothing to compare. "
            "Critique, the one-page answer and the memory update were skipped."
        )
        return None

    # Critique
    critics = [result.seat for result in results if result.ok]
    review_tokens = critique_max_tokens(answer_tokens)
    longest = max(
        messages_tokens(critique_messages(question, today, [a for a in answers if a is not own]))
        for own in answers
    )
    reviewers = [seat.member for seat in critics]
    if _would_exceed(outcome, catalog, reviewers, longest, review_tokens, cap):
        _stop(outcome, "critique", catalog, reviewers, longest, review_tokens, cap)
        return None

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
    messages = synthesis_messages(question, today, answers, reviews, table, context.recall_text)
    page_tokens = synthesis_max_tokens(answer_tokens)
    prompt_tokens = messages_tokens(messages)
    if _would_exceed(outcome, catalog, [chairman.member], prompt_tokens, page_tokens, cap):
        _stop(outcome, "synthesis", catalog, [chairman.member], prompt_tokens, page_tokens, cap)
        return None

    result = await ask_one(client, chairman, messages, page_tokens)
    outcome.calls.append(_record(Call("synthesis", result), catalog))
    if result.completion is None:
        outcome.notes.append(
            f"The chairman could not write the one-page answer ({result.error}). "
            "The answers and reviews are saved; the memory was not changed."
        )
        return None

    text = final_page(
        question,
        result.completion.text,
        context.started.strftime("%Y-%m-%d %H:%M"),
        context.profile_name,
        chairman.member.model,
        table,
        reviews,
    )
    write_final(run, text)
    outcome.calls[-1].file = "final.md"
    outcome.final_text = text
    outcome.stages.append("synthesis")
    return result.completion.text


async def _update_memory(
    outcome: Outcome,
    client: OpenRouterClient,
    run: Run,
    context: _Context,
    chairman: Seat,
    body: str,
    approve: Approve | None,
) -> None:
    """Ask the chairman for a memory patch, apply it under the rules, and record what changed."""
    memory = context.memory
    assert memory is not None
    today = context.started.date()
    messages = memory_messages(run.topic, memory_listing(memory), body, today)
    prompt_tokens = messages_tokens(messages)
    if _would_exceed(
        outcome, context.catalog, [chairman.member], prompt_tokens, MEMORY_MAX_TOKENS, context.cap
    ):
        _stop(
            outcome,
            "memory update",
            context.catalog,
            [chairman.member],
            prompt_tokens,
            MEMORY_MAX_TOKENS,
            context.cap,
        )
        _append_memory_section(outcome, run, ["The memory was not changed: the run hit its cap."])
        return

    result = await ask_one(client, chairman, messages, MEMORY_MAX_TOKENS)
    outcome.calls.append(_record(Call("memory", result), context.catalog))
    if result.completion is None:
        outcome.notes.append(f"The memory update failed ({result.error}); the memory is unchanged.")
        _append_memory_section(outcome, run, ["The memory was not changed: the update failed."])
        return

    patch = None if result.completion.cut_off else parse_patch(result.completion.text)
    if patch is None:
        (run.path / "memory_reply.md").write_text(result.completion.text + "\n", encoding="utf-8")
        why = (
            "was cut off at the length limit"
            if result.completion.cut_off
            else "was not in the expected form"
        )
        outcome.notes.append(
            f"The memory update reply {why}, so the memory is unchanged. "
            "The reply is saved as memory_reply.md."
        )
        _append_memory_section(
            outcome, run, ["The memory was not changed: the reply was unreadable."]
        )
        return

    proposed = copy.deepcopy(memory)
    changes = apply_patch(proposed, patch, run.path.name, today)
    record: dict[str, Any] = {
        "proposed": patch,
        "applied": changes.lines(),
        "skipped": changes.skipped,
        "approved": None,
    }

    if not changes.empty and approve is not None:
        record["approved"] = approve(changes)
        if not record["approved"]:
            write_json(run, "memory_patch.json", record)
            outcome.notes.append("You declined the memory changes, so the memory is unchanged.")
            _append_memory_section(
                outcome, run, ["Proposed changes were declined; none were saved."]
            )
            return

    write_json(run, "memory_patch.json", record)
    outcome.changes = changes
    if not changes.empty:
        save_memory(context.topic_dir, proposed)
        context.memory = proposed
    outcome.stages.append("memory")
    _append_memory_section(outcome, run, changes.lines() or ["No changes."])


def _append_memory_section(outcome: Outcome, run: Run, lines: list[str]) -> None:
    if outcome.final_text is None:
        return
    section = "\n## What changed in memory\n\n" + "\n".join(lines) + "\n"
    outcome.final_text = outcome.final_text.rstrip("\n") + "\n" + section
    write_final(run, outcome.final_text)


def _commit(outcome: Outcome, store: Path, run: Run, topic_dir: Path, question: str) -> None:
    paths = [run.path] + [
        topic_dir / name
        for name in ("memory.json", "summary.md", "disputes.md", "notes.md")
        if (topic_dir / name).exists()
    ]
    short = " ".join(question.split())
    message = f"conclave: {short[:68]}{'...' if len(short) > 68 else ''}"
    problem = commit(store, paths, message)
    if problem:
        outcome.notes.append(problem)


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
    cut = [
        f"{call.stage} by {call.result.seat.member.model}"
        for call in outcome.calls
        if call.result.completion is not None and call.result.completion.cut_off
    ]
    if cut:
        outcome.notes.append(
            "Cut off at the length limit, so incomplete: "
            + "; ".join(cut)
            + ". Other models were told. Raise run.max_answer_tokens if this keeps happening."
        )
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
                reasoning_tokens=done.reasoning_tokens,
                cut_off=done.cut_off,
                seconds=round(done.seconds, 2),
                file=call.file,
            )
        calls.append(record)

    recall = outcome.recall
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
            "recall": None
            if recall is None
            else {
                "claims": recall.claims,
                "disputes": recall.disputes,
                "notes": recall.has_notes,
                "truncated": recall.truncated,
            },
            "memory_changes": None if outcome.changes is None else outcome.changes.lines(),
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
