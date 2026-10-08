"""The Verify stage: pick the key claims, test each against the pages cited for it, and label it.

The model proposes; code decides. The checker's verdicts count only when the words it
quotes are really in the page, and every claim's label is worked out here from the
verdict and from how many members and sources stand behind it (decision 0005).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from conclave.council import Labeled, Review, load_prompt
from conclave.sources import CitedSource, best_passage, domain, found_in

# "unreachable": sources were cited but none could be read. "no source": none was cited.
VERDICTS = ("supported", "contradicted", "not found", "unreachable", "no source")

# Labels a claim can carry on the final page. Only the first two may enter memory.
LABELS = ("verified", "agreed but unchecked", "single source", "single model", "disputed")


@dataclass
class CheckedClaim:
    number: int
    text: str
    responses: list[str]
    sources: list[str]  # S numbers
    disagreement: bool
    verdict: str = "unreachable"
    source: str | None = None  # the S number the verdict rests on
    quote: str = ""
    note: str = ""
    label: str = "single model"
    passages: dict[str, tuple[str, str]] = field(default_factory=dict)  # S -> (kind, text)


def source_ids(pages: list[CitedSource]) -> dict[str, CitedSource]:
    return {f"S{n}": page for n, page in enumerate(pages, start=1)}


def _json_object(text: str) -> dict[str, Any] | None:
    candidates = re.findall(r"```(?:json)?\s*(\{.*\})\s*```", text, re.DOTALL)
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


# --- picking the claims -------------------------------------------------------------


def extract_messages(
    question: str,
    today: date,
    answers: list[Labeled],
    reviews: list[Review],
    ids: dict[str, CitedSource],
    limit: int,
) -> list[dict[str, str]]:
    listing = "\n".join(
        f"- {sid}: {page.url}"
        + (f" ({page.title})" if page.title else "")
        + f", cited by {', '.join(page.cited_by)}"
        for sid, page in ids.items()
    )
    responses = "\n\n".join(f"### Response {a.letter}\n\n{a.text}" for a in answers)
    critiques = "\n\n".join(
        f"### Review by the author of Response {r.letter}\n\n{r.result.completion.text}"
        for r in reviews
        if r.result.completion is not None
    )
    user = (
        f"Today's date: {today.isoformat()}\n\nQuestion: {question}\n\n"
        f"Pick at most {limit} claims.\n\n"
        f"## Sources the members cited\n\n{listing or 'None.'}\n\n"
        f"## The members' answers\n\n{responses}\n\n"
        f"## The members' reviews of each other\n\n{critiques or 'None.'}"
    )
    return [
        {"role": "system", "content": load_prompt("extract")},
        {"role": "user", "content": user},
    ]


def parse_claims(
    text: str, letters: list[str], ids: dict[str, CitedSource], limit: int
) -> list[CheckedClaim] | None:
    """The claims the checker picked. None if the reply is unreadable.

    Unknown response letters and source numbers are dropped, never trusted.
    """
    data = _json_object(text)
    if data is None or not isinstance(data.get("claims"), list):
        return None
    claims: list[CheckedClaim] = []
    for item in data["claims"]:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        sentence = " ".join(item["text"].split())
        if not sentence:
            continue
        responses = [
            r
            for r in dict.fromkeys(str(x).strip().upper() for x in item.get("responses") or [])
            if r in letters
        ]
        if not responses:
            continue
        cited = [
            s
            for s in dict.fromkeys(str(x).strip().upper() for x in item.get("sources") or [])
            if s in ids
        ]
        claims.append(
            CheckedClaim(
                number=len(claims) + 1,
                text=sentence,
                responses=responses,
                sources=cited,
                disagreement=item.get("disagreement") is True,
            )
        )
        if len(claims) == limit:
            break
    return claims


# --- checking them --------------------------------------------------------------------


def attach_passages(
    claims: list[CheckedClaim], ids: dict[str, CitedSource], per_claim: int
) -> None:
    """Give each claim the most relevant part of each of its sources, fetched page first."""
    for claim in claims:
        if not claim.sources:
            claim.verdict = "no source"
        for sid in claim.sources[:per_claim]:
            page = ids[sid]
            if page.fetched and page.text:
                claim.passages[sid] = ("fetched page", best_passage(claim.text, page.text))
            elif page.excerpt:
                claim.passages[sid] = (
                    "search excerpt only",
                    best_passage(claim.text, page.excerpt),
                )


def check_messages(
    question: str, claims: list[CheckedClaim], ids: dict[str, CitedSource]
) -> list[dict[str, str]]:
    parts = []
    for claim in claims:
        block = [f"## Claim {claim.number}\n\n{claim.text}"]
        for sid, (kind, passage) in claim.passages.items():
            block.append(f"### {sid}: {ids[sid].url} ({kind})\n\n{passage}")
        parts.append("\n\n".join(block))
    user = f"The question these claims answer: {question}\n\n" + "\n\n".join(parts)
    return [
        {"role": "system", "content": load_prompt("check")},
        {"role": "user", "content": user},
    ]


def apply_verdicts(text: str, claims: list[CheckedClaim]) -> bool:
    """Record the checker's verdicts. Returns False if the reply is unreadable.

    A verdict stands only if its quote is in the passage it names; otherwise the claim
    is "not found". Claims the checker skipped stay "not found".
    """
    data = _json_object(text)
    if data is None or not isinstance(data.get("verdicts"), list):
        return False
    by_number = {c.number: c for c in claims if c.passages}
    for claim in by_number.values():
        claim.verdict = "not found"
    for item in data["verdicts"]:
        if not isinstance(item, dict):
            continue
        try:
            number = int(item.get("claim"))
        except (TypeError, ValueError):
            continue
        claim = by_number.get(number)
        if claim is None:
            continue
        verdict = str(item.get("verdict", "")).strip().lower()
        note = " ".join(str(item.get("note") or "").split())
        if verdict not in ("supported", "contradicted"):
            claim.verdict, claim.note = "not found", note
            continue
        sid = str(item.get("source", "")).strip().upper()
        quote = " ".join(str(item.get("quote") or "").split())
        passage = claim.passages.get(sid)
        if passage is None or not found_in(quote, passage[1]):
            claim.verdict = "not found"
            claim.note = (
                f"The checker said {verdict}, but its quote is not in the source, "
                "so the verdict was not accepted."
            )
            continue
        claim.verdict, claim.source, claim.quote, claim.note = verdict, sid, quote, note
    return True


def label(claim: CheckedClaim, ids: dict[str, CitedSource]) -> str:
    """The label a checked claim earns, worked out in code.

    Contradicted by a source, or disputed among members and not settled by one: disputed.
    Supported by a source: verified. Otherwise it rests on agreement: agreed but unchecked
    when two or more members back it from two or more websites, single source when all of
    them lean on one website, single model when only one member makes it.
    """
    if claim.verdict == "contradicted":
        return "disputed"
    if claim.verdict == "supported":
        return "verified"
    if claim.disagreement:
        return "disputed"
    if len(claim.responses) < 2:
        return "single model"
    sites = {domain(ids[s].url) for s in claim.sources}
    if len(sites) == 1:
        return "single source"
    return "agreed but unchecked"


# --- what the chairman and the user see -------------------------------------------------


def chairman_block(claims: list[CheckedClaim], ids: dict[str, CitedSource]) -> str:
    """The checked claims as the chairman sees them, with the labels it must use."""
    if not claims:
        return ""
    lines = []
    for c in claims:
        line = f"{c.number}. {c.text} [{c.label}] (responses {', '.join(c.responses)}; {c.verdict}"
        if c.source:
            line += f' by {ids[c.source].url}: "{c.quote}"'
        lines.append(line + ")")
    return "\n".join(lines)


def render(claims: list[CheckedClaim], ids: dict[str, CitedSource], checker: str) -> str:
    """verification.md: every checked claim, its verdict, the evidence and its label."""
    counts = {v: sum(1 for c in claims if c.verdict == v) for v in VERDICTS}
    lines = [
        "# Claim checks",
        "",
        f"The checker, `{checker}`, tested {len(claims)} key claims against the pages the "
        "members cited. A verdict counts only if the words it quotes are in the page.",
        "",
        f"Supported: {counts['supported']}. Contradicted: {counts['contradicted']}. "
        f"Not found in the sources: {counts['not found']}. "
        f"Sources could not be read: {counts['unreachable']}. "
        f"No source cited: {counts['no source']}.",
        "",
        "| # | Claim | Responses | Verdict | Label |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in claims:
        lines.append(
            f"| {c.number} | {c.text} | {', '.join(c.responses)} | {c.verdict} | {c.label} |"
        )
    for c in claims:
        lines += ["", f"## {c.number}. {c.text}", ""]
        if not c.sources:
            lines.append("No source was cited for this claim.")
        for sid in c.sources:
            page = ids[sid]
            if sid in c.passages:
                how = c.passages[sid][0]
                if not page.fetched and page.fetch_error:
                    how += f"; the page could not be fetched: {page.fetch_error}"
            elif page.fetch_error:
                how = f"not read: {page.fetch_error}, and the search gave no excerpt"
            else:
                how = "not read: beyond the sources checked for one claim"
            lines.append(f"- {sid} <{page.url}> ({how})")
        if c.quote:
            lines += ["", f"> {c.quote}", "", f"*{c.verdict.capitalize()} by {c.source}.*"]
        if c.note:
            lines += ["", c.note]
    return "\n".join(lines) + "\n"
