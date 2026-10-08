"""The local research store: plain files on the user's own disk.

Each question is saved as a run folder under its topic. The topic's memory
(claims, disputes and notes) lives beside the runs; see memory.py.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_TOPIC = "general"

STORE_README = """\
# Conclave research store

This folder is your private research memory. Conclave reads it before every
question on a topic and writes back to it after every full run.

- Keep it out of any public repository.
- Make it its own private Git repository if you want history and backup:
  run `git init` here.
- Everything is plain text. You can read and edit any file yourself.

Layout (filled in as you use Conclave):

    topics/
      <topic>/
        summary.md     what the council has concluded, one claim per line
        disputes.md    disagreements, each marked open or resolved
        memory.json    the record summary.md and disputes.md are written from
        notes.md       your own notes; the council reads these first
        runs/          one folder per question, never edited afterwards
    index.sqlite       search index, rebuilt from the files whenever needed

summary.md and disputes.md are rewritten after every full run. To correct the
council, add a note (conclave note <topic> "...") rather than editing them.
"""


def init_store(path: Path) -> list[Path]:
    """Create the store folder if needed. Returns what was created, in order.

    Safe to run again: existing folders and files are left untouched.
    """
    created: list[Path] = []
    topics = path / "topics"
    readme = path / "README.md"

    if not path.exists():
        path.mkdir(parents=True)
        created.append(path)
    if not topics.exists():
        topics.mkdir()
        created.append(topics)
    if not readme.exists():
        readme.write_text(STORE_README, encoding="utf-8")
        created.append(readme)
    return created


def slugify(text: str, max_words: int = 8, max_length: int = 60, fallback: str = "untitled") -> str:
    """Turn any text into a short lowercase name that is safe as a folder name everywhere."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", plain.lower())[:max_words]
    slug = "-".join(words)[:max_length].strip("-")
    return slug or fallback


def model_filename(model_id: str) -> str:
    """A file name for a model's answer: 'vendor/model' becomes 'vendor--model.md'."""
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", model_id.replace("/", "--")).strip("-")
    return f"{safe or 'model'}.md"


@dataclass(frozen=True)
class Run:
    """One question's folder. Written once and never edited afterwards."""

    path: Path
    topic: str

    @property
    def answers(self) -> Path:
        return self.path / "answers"


def create_run(store: Path, topic: str, question: str, started: datetime) -> Run:
    """Create a new run folder: topics/<topic>/runs/<date-time>-<question>/"""
    topic_slug = slugify(topic, fallback=DEFAULT_TOPIC)
    runs = store / "topics" / topic_slug / "runs"
    base = f"{started:%Y-%m-%d-%H%M%S}-{slugify(question, fallback='question')}"

    path = runs / base
    counter = 2
    while path.exists():
        path = runs / f"{base}-{counter}"
        counter += 1
    (path / "answers").mkdir(parents=True)
    return Run(path=path, topic=topic_slug)


def write_question(run: Run, question: str, details: dict[str, str]) -> Path:
    lines = ["# Question", "", question.strip(), ""]
    lines += [f"- {label}: {value}" for label, value in details.items()]
    target = run.path / "question.md"
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def write_model_text(
    run: Run, folder: str, model_id: str, details: dict[str, str], text: str
) -> Path:
    """Save one model's text under a stage folder, with a small header saying who wrote it."""
    directory = run.path / folder
    directory.mkdir(exist_ok=True)
    target = directory / model_filename(model_id)
    counter = 2
    while target.exists():  # the same model seated twice in one run
        target = directory / model_filename(f"{model_id}-{counter}")
        counter += 1
    lines = ["---", f"model: {model_id}"] + [f"{key}: {value}" for key, value in details.items()]
    header = "\n".join(lines) + "\n---\n\n"
    target.write_text(header + text.strip() + "\n", encoding="utf-8")
    return target


def write_answer(run: Run, model_id: str, role: str, text: str, letter: str | None = None) -> Path:
    details = {"role": role}
    if letter:
        details["response"] = letter
    return write_model_text(run, "answers", model_id, details, text)


def write_review(run: Run, model_id: str, letter: str, reviewed: list[str], text: str) -> Path:
    details = {"role": "reviewer", "own_response": letter, "reviewed": ", ".join(reviewed)}
    return write_model_text(run, "critiques", model_id, details, text)


def write_json(run: Run, name: str, data: Any) -> Path:
    target = run.path / name
    target.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return target


def write_final(run: Run, text: str) -> Path:
    target = run.path / "final.md"
    target.write_text(text.strip() + "\n", encoding="utf-8")
    return target


def write_meta(run: Run, meta: dict[str, Any]) -> Path:
    return write_json(run, "meta.json", meta)


def month_spend(store: Path, now: datetime) -> float:
    """Total recorded cost of every run started in the same calendar month as `now`."""
    total = 0.0
    for meta_file in store.glob("topics/*/runs/*/meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            started = datetime.fromisoformat(meta["started"])
            cost = meta["totals"]["cost_usd"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if (started.year, started.month) == (now.year, now.month) and isinstance(cost, int | float):
            total += float(cost)
    return total
