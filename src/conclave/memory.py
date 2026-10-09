"""A topic's memory: the claims earlier runs concluded, open disputes, and the user's notes.

The structured record lives in memory.json. summary.md and disputes.md are written
from it after every change, so they always agree with it. notes.md belongs to the
user and is only ever appended to.
"""

from __future__ import annotations

import json
import os
import re
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from conclave.store import atomic_write

MEMORY_FILE = "memory.json"
SUMMARY_FILE = "summary.md"
DISPUTES_FILE = "disputes.md"
NOTES_FILE = "notes.md"

# Labels a claim may carry in memory. "verified" arrives with claim checking.
ENTRY_LABELS = ("agreed but unchecked", "verified")

# Recall is cut at this many characters so it never crowds out the question.
RECALL_CHAR_LIMIT = 12_000


class MemoryFileError(Exception):
    """memory.json is unreadable. The message says where."""


# Threads that already hold a topic's lock. flock is not re-entrant across two opens,
# and a run holds the lock from the moment it reads the memory until it writes it back.
_HELD = threading.local()


def _lock_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        if os.fstat(fd).st_size < 1:
            os.write(fd, b"\0")
            os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock_fd(fd: int) -> None:
    if sys.platform == "win32":
        import msvcrt

        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def topic_lock(topic_dir: Path) -> Iterator[None]:
    """One writer at a time for a topic, across threads and processes."""
    topic_dir = Path(topic_dir)
    lock_path = (topic_dir.parent / f".{topic_dir.name}.lock").resolve()
    held: set[Path] | None = getattr(_HELD, "paths", None)
    if held is None:
        held = set()
        _HELD.paths = held
    if lock_path in held:
        yield
        return
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
    try:
        _lock_fd(fd)
        held.add(lock_path)
        try:
            yield
        finally:
            held.discard(lock_path)
            _unlock_fd(fd)
    finally:
        os.close(fd)


@dataclass
class Claim:
    id: str
    text: str
    label: str
    added: str  # ISO date
    added_run: str
    updated: str | None = None
    updated_run: str | None = None
    history: list[dict[str, str]] = field(default_factory=list)
    retired: str | None = None  # ISO date
    retired_run: str | None = None
    retired_reason: str | None = None

    @property
    def active(self) -> bool:
        return self.retired is None


@dataclass
class Dispute:
    id: str
    text: str
    opened: str
    opened_run: str
    resolved: str | None = None
    resolved_run: str | None = None
    resolution: str | None = None

    @property
    def open(self) -> bool:
        return self.resolved is None


@dataclass
class TopicMemory:
    topic: str
    claims: list[Claim] = field(default_factory=list)
    disputes: list[Dispute] = field(default_factory=list)

    @property
    def active_claims(self) -> list[Claim]:
        return [c for c in self.claims if c.active]

    @property
    def open_disputes(self) -> list[Dispute]:
        return [d for d in self.disputes if d.open]

    def claim(self, claim_id: str) -> Claim | None:
        return next((c for c in self.claims if c.id == claim_id), None)

    def dispute(self, dispute_id: str) -> Dispute | None:
        return next((d for d in self.disputes if d.id == dispute_id), None)

    def next_claim_id(self) -> str:
        return f"C{len(self.claims) + 1}"

    def next_dispute_id(self) -> str:
        return f"D{len(self.disputes) + 1}"


# --- load and save --------------------------------------------------------------


def load_memory(topic_dir: Path, topic: str) -> TopicMemory:
    path = topic_dir / MEMORY_FILE
    if not path.is_file():
        return TopicMemory(topic=topic)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return TopicMemory(
            topic=topic,
            claims=[Claim(**item) for item in data.get("claims", [])],
            disputes=[Dispute(**item) for item in data.get("disputes", [])],
        )
    except (OSError, ValueError, TypeError) as error:
        raise MemoryFileError(
            f"{path} could not be read ({error}). Restore it from Git history, "
            "or move it aside to start the topic's memory again."
        ) from None


def save_memory(topic_dir: Path, memory: TopicMemory) -> list[Path]:
    """Write memory.json, summary.md and disputes.md. Returns the paths written.

    The topic lock is held, and each file is replaced in one step, so a crash or a
    second run cannot leave a half-written memory.
    """
    with topic_lock(topic_dir):
        topic_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "topic": memory.topic,
            "claims": [vars(c) for c in memory.claims],
            "disputes": [vars(d) for d in memory.disputes],
        }
        written = []
        for name, text in (
            (MEMORY_FILE, json.dumps(data, indent=2) + "\n"),
            (SUMMARY_FILE, render_summary(memory)),
            (DISPUTES_FILE, render_disputes(memory)),
        ):
            target = topic_dir / name
            atomic_write(target, text)
            written.append(target)
        return written


def render_summary(memory: TopicMemory) -> str:
    lines = [
        f"# {memory.topic}: what the council has concluded",
        "",
        "*Written by Conclave from memory.json after every full run; edits here are "
        "overwritten. To correct the council, add a line to notes.md instead.*",
        "",
    ]
    active = memory.active_claims
    if not active:
        lines.append("No claims yet.")
    for claim in active:
        when = claim.updated or claim.added
        run = claim.updated_run or claim.added_run
        lines.append(f"- **{claim.id}** {claim.text} [{claim.label}] *({when}, run {run})*")
    retired = [c for c in memory.claims if not c.active]
    if retired:
        lines += ["", "## Retired", ""]
        for claim in retired:
            reason = claim.retired_reason
            lines.append(f"- ~~**{claim.id}** {claim.text}~~ *Retired {claim.retired}: {reason}*")
    return "\n".join(lines) + "\n"


def render_disputes(memory: TopicMemory) -> str:
    lines = [f"# {memory.topic}: disputes", "", "*Written by Conclave from memory.json.*", ""]
    if not memory.disputes:
        lines.append("No disputes yet.")
    open_ = memory.open_disputes
    if open_:
        lines += ["## Open", ""]
        lines += [f"- **{d.id}** {d.text} *(opened {d.opened}, run {d.opened_run})*" for d in open_]
    resolved = [d for d in memory.disputes if not d.open]
    if resolved:
        lines += ["", "## Resolved", ""]
        lines += [
            f"- **{d.id}** {d.text} *Resolved {d.resolved}: {d.resolution}*" for d in resolved
        ]
    return "\n".join(lines) + "\n"


# --- notes ----------------------------------------------------------------------


def read_notes(topic_dir: Path) -> str:
    path = topic_dir / NOTES_FILE
    return path.read_text(encoding="utf-8").strip() if path.is_file() else ""


def add_note(topic_dir: Path, topic: str, text: str, today: date) -> Path:
    """Append a dated note. notes.md is the user's own file; it is never rewritten."""
    with topic_lock(topic_dir):
        path = topic_dir / NOTES_FILE
        topic_dir.mkdir(parents=True, exist_ok=True)
        if not path.is_file():
            path.write_text(
                f"# {topic}: notes\n\n*Your own notes. The council reads them before every "
                "question on this topic, and they take precedence over its conclusions.*\n\n",
                encoding="utf-8",
            )
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"- {today.isoformat()}: {text.strip()}\n")
        return path


# --- recall ---------------------------------------------------------------------


@dataclass(frozen=True)
class Recall:
    text: str  # empty when the topic has no memory yet
    claims: int
    disputes: int
    has_notes: bool
    truncated: bool


def build_recall(topic_dir: Path, memory: TopicMemory) -> Recall:
    """The text given to the council before it answers: notes first, then claims and disputes."""
    notes = read_notes(topic_dir)
    parts: list[str] = []
    if notes:
        parts.append(
            "### The user's own notes (these take precedence over earlier conclusions)\n\n" + notes
        )
    if memory.active_claims:
        parts.append(
            "### Claims from earlier runs\n\n"
            + "\n".join(f"- {c.id}: {c.text} [{c.label}]" for c in memory.active_claims)
        )
    if memory.open_disputes:
        parts.append(
            "### Open disputes from earlier runs\n\n"
            + "\n".join(f"- {d.id}: {d.text}" for d in memory.open_disputes)
        )
    text = "\n\n".join(parts)
    truncated = len(text) > RECALL_CHAR_LIMIT
    if truncated:
        text = text[:RECALL_CHAR_LIMIT].rsplit("\n", 1)[0] + "\n\n(Earlier research cut short.)"
    return Recall(
        text=text,
        claims=len(memory.active_claims),
        disputes=len(memory.open_disputes),
        has_notes=bool(notes),
        truncated=truncated,
    )


def memory_listing(memory: TopicMemory) -> str:
    """Current claims and disputes with their ids, for the memory-update prompt."""
    claims = "\n".join(f"- {c.id}: {c.text} [{c.label}]" for c in memory.active_claims)
    disputes = "\n".join(f"- {d.id}: {d.text}" for d in memory.open_disputes)
    return (
        f"## Current claims\n\n{claims or 'None yet.'}\n\n## Open disputes\n\n{disputes or 'None.'}"
    )


# --- patches --------------------------------------------------------------------

PATCH_KEYS = ("add", "change", "retire", "open_disputes", "resolve_disputes")
_FENCE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)


def parse_patch(text: str) -> dict[str, list[dict[str, Any]]] | None:
    """Read the JSON patch from a model's reply. None if it is not a usable patch."""
    candidates = [m.group(1) for m in _FENCE.finditer(text)]
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        candidates.append(text[start : end + 1])
    for candidate in candidates:
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict) and any(key in data for key in PATCH_KEYS):
            return {
                key: [i for i in data.get(key, []) if isinstance(i, dict)] for key in PATCH_KEYS
            }
    return None


@dataclass
class Changes:
    """What a patch did to the memory, for the user to read."""

    added: list[Claim] = field(default_factory=list)
    changed: list[tuple[Claim, str]] = field(default_factory=list)  # claim, previous text
    retired: list[Claim] = field(default_factory=list)
    opened: list[Dispute] = field(default_factory=list)
    resolved: list[Dispute] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    similar: dict[str, str] = field(default_factory=dict)  # new claim id -> claim it may repeat

    @property
    def empty(self) -> bool:
        return not (self.added or self.changed or self.retired or self.opened or self.resolved)

    def lines(self) -> list[str]:
        out = [
            f"- Added {c.id}: {c.text} [{c.label}]"
            + (f" (may repeat {self.similar[c.id]})" if c.id in self.similar else "")
            for c in self.added
        ]
        out += [f"- Changed {c.id}: {c.text} [{c.label}] (was: {old})" for c, old in self.changed]
        out += [f"- Retired {c.id}: {c.text} ({c.retired_reason})" for c in self.retired]
        out += [f"- Opened dispute {d.id}: {d.text}" for d in self.opened]
        out += [f"- Resolved dispute {d.id}: {d.text} ({d.resolution})" for d in self.resolved]
        return out


def _clean(value: Any) -> str:
    return " ".join(str(value).split()) if isinstance(value, str) else ""


# Word overlap between two claims: the share of the shorter claim's content words that the
# other also has. It is a rough guide, so only near-identical claims are refused; a likely
# repeat is added but flagged, for the user to see.
SAME_CLAIM = 0.85
SIMILAR_CLAIM = 0.6
# A claim stored as verified must not say much more than the claim that was checked: this
# share of its own content words must appear in a verified claim or the quote behind it.
VERIFIED_COVERAGE = 0.75


def overlap(a: str, b: str) -> float:
    """Share of the shorter claim's content words that the other claim also has."""
    from conclave.sources import words

    left, right = words(a), words(b)
    if not left or not right:
        return 0.0
    return len(left & right) / min(len(left), len(right))


def covered(claim: str, evidence: str) -> float:
    """Share of a claim's own content words that also appear in the evidence."""
    from conclave.sources import words

    own = words(claim)
    return len(own & words(evidence)) / len(own) if own else 0.0


def _same(a: str, b: str) -> bool:
    return re.sub(r"\W+", " ", a).strip().lower() == re.sub(r"\W+", " ", b).strip().lower()


def apply_patch(
    memory: TopicMemory,
    patch: dict[str, list[dict[str, Any]]],
    run: str,
    today: date,
    verified: list[str] | None = None,
) -> Changes:
    """Apply a patch, enforcing the memory rules in code. The model's reply is never trusted.

    Changes and retirements are applied before additions, so a new claim is compared with
    claims as just changed. `verified` lists the claims this run's checker verified, each with
    its quote; a claim labelled "verified" that says much more than any of them is stored
    as "agreed but unchecked".
    None means no checking took place, and the label is taken as given.
    """
    changes = Changes()
    stamp = today.isoformat()

    for item in patch.get("change", []):
        claim = memory.claim(_clean(item.get("id")))
        text, label = _clean(item.get("text")), _clean(item.get("label")).lower()
        reason = _clean(item.get("reason"))
        if claim is None or not claim.active or not text:
            changes.skipped.append(f"Change ignored, no such active claim: {item.get('id')}")
            continue
        if label not in ENTRY_LABELS:
            changes.skipped.append(f"Change to {claim.id} ignored, labelled '{label or 'none'}'")
            continue
        if (
            label == "verified"
            and verified is not None
            and not any(covered(text, v) >= VERIFIED_COVERAGE for v in verified)
        ):
            label = "agreed but unchecked"
        previous = claim.text
        claim.history.append({"date": stamp, "run": run, "text": previous, "reason": reason})
        claim.text, claim.label, claim.updated, claim.updated_run = text, label, stamp, run
        changes.changed.append((claim, previous))

    for item in patch.get("retire", []):
        claim = memory.claim(_clean(item.get("id")))
        reason = _clean(item.get("reason"))
        if claim is None or not claim.active:
            changes.skipped.append(f"Retire ignored, no such active claim: {item.get('id')}")
            continue
        if not reason:
            changes.skipped.append(f"Retire of {claim.id} ignored, no reason given")
            continue
        claim.retired, claim.retired_run, claim.retired_reason = stamp, run, reason
        changes.retired.append(claim)

    for item in patch.get("add", []):
        text, label = _clean(item.get("text")), _clean(item.get("label")).lower()
        if not text:
            continue
        if label not in ENTRY_LABELS:
            changes.skipped.append(f"Not added, labelled '{label or 'none'}': {text}")
            continue
        if (
            label == "verified"
            and verified is not None
            and not any(covered(text, v) >= VERIFIED_COVERAGE for v in verified)
        ):
            label = "agreed but unchecked"
            changes.skipped.append(
                f"Label changed to 'agreed but unchecked', no matching verified claim: {text}"
            )
        scores = sorted(((overlap(text, c.text), c.id) for c in memory.active_claims), reverse=True)
        if scores and scores[0][0] >= SAME_CLAIM:
            changes.skipped.append(f"Not added, repeats {scores[0][1]}: {text}")
            continue
        claim = Claim(memory.next_claim_id(), text, label, stamp, run)
        memory.claims.append(claim)
        changes.added.append(claim)
        if scores and scores[0][0] >= SIMILAR_CLAIM:
            changes.similar[claim.id] = scores[0][1]

    for item in patch.get("open_disputes", []):
        text = _clean(item.get("text"))
        if not text or any(_same(text, d.text) for d in memory.open_disputes):
            continue
        dispute = Dispute(memory.next_dispute_id(), text, stamp, run)
        memory.disputes.append(dispute)
        changes.opened.append(dispute)

    for item in patch.get("resolve_disputes", []):
        dispute = memory.dispute(_clean(item.get("id")))
        resolution = _clean(item.get("resolution"))
        if dispute is None or not dispute.open or not resolution:
            changes.skipped.append(f"Resolve ignored: {item.get('id')}")
            continue
        dispute.resolved, dispute.resolved_run, dispute.resolution = stamp, run, resolution
        changes.resolved.append(dispute)

    return changes
