"""Reading the research store: topics, search and the personal leaderboard."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

from conclave.memory import load_memory

INDEX_FILE = "index.sqlite"
INDEXED = {
    "final.md": "final answer",
    "question.md": "question",
    "summary.md": "summary",
    "disputes.md": "disputes",
    "notes.md": "notes",
}


@dataclass(frozen=True)
class TopicInfo:
    name: str
    runs: int
    full_runs: int
    claims: int
    open_disputes: int
    has_notes: bool
    last_run: str | None


def run_mode(run: Path) -> str:
    """The mode a run was asked in, as recorded in its meta.json."""
    try:
        mode = json.loads((run / "meta.json").read_text(encoding="utf-8")).get("mode")
    except (OSError, ValueError, AttributeError):
        mode = None
    if mode in ("quick", "full"):
        return mode
    return "full" if (run / "final.md").exists() else "quick"


def topics(store: Path) -> list[TopicInfo]:
    root = store / "topics"
    if not root.is_dir():
        return []
    found = []
    for folder in sorted(p for p in root.iterdir() if p.is_dir()):
        runs = sorted((folder / "runs").glob("*/meta.json")) if (folder / "runs").is_dir() else []
        full = sum(1 for m in runs if run_mode(m.parent) == "full")
        memory = load_memory(folder, folder.name)
        found.append(
            TopicInfo(
                name=folder.name,
                runs=len(runs),
                full_runs=full,
                claims=len(memory.active_claims),
                open_disputes=len(memory.open_disputes),
                has_notes=(folder / "notes.md").is_file(),
                last_run=runs[-1].parent.name[:10] if runs else None,
            )
        )
    return found


# --- search ---------------------------------------------------------------------


def _documents(store: Path) -> list[tuple[str, str, str, float]]:
    """Every indexed file: (path relative to the store, kind, text, modified time)."""
    docs = []
    root = store / "topics"
    if not root.is_dir():
        return docs
    for path in root.rglob("*.md"):
        kind = INDEXED.get(path.name)
        if path.parent.name == "answers":
            kind = "answer"
        if kind is None:
            continue
        docs.append(
            (
                path.relative_to(store).as_posix(),
                kind,
                path.read_text(encoding="utf-8", errors="replace"),
                path.stat().st_mtime,
            )
        )
    return docs


def _fts_available(connection: sqlite3.Connection) -> bool:
    try:
        connection.execute("CREATE VIRTUAL TABLE temp.probe USING fts5(x)")
        connection.execute("DROP TABLE temp.probe")
        return True
    except sqlite3.OperationalError:
        return False


@dataclass(frozen=True)
class Hit:
    path: str
    topic: str
    kind: str
    snippet: str


def refresh_index(store: Path) -> Path:
    """Rebuild the index from the files if any file is newer than it. It is never the source."""
    index = store / INDEX_FILE
    docs = _documents(store)
    newest = max((d[3] for d in docs), default=0.0)
    if index.exists() and index.stat().st_mtime >= newest:
        try:
            with closing(sqlite3.connect(index)) as connection:
                count = connection.execute("SELECT count(*) FROM meta").fetchone()[0]
            if count == len(docs):
                return index
        except sqlite3.Error:
            pass  # a damaged index is simply rebuilt
    # sqlite3's own context manager commits but does not close, and Windows will not
    # delete a file that is still open, so every connection here is closed explicitly.
    index.unlink(missing_ok=True)
    with closing(sqlite3.connect(index)) as connection, connection:
        fts = _fts_available(connection)
        connection.execute("CREATE TABLE meta (path TEXT PRIMARY KEY, fts INTEGER)")
        if fts:
            connection.execute("CREATE VIRTUAL TABLE docs USING fts5(path, topic, kind, body)")
        else:
            connection.execute("CREATE TABLE docs (path TEXT, topic TEXT, kind TEXT, body TEXT)")
        for path, kind, text, _ in docs:
            topic = path.split("/")[1]
            connection.execute("INSERT INTO docs VALUES (?, ?, ?, ?)", (path, topic, kind, text))
            connection.execute("INSERT INTO meta VALUES (?, ?)", (path, int(fts)))
    return index


def _snippet(text: str, words: list[str], width: int = 160) -> str:
    lower = text.lower()
    at = min((i for i in (lower.find(w.lower()) for w in words) if i >= 0), default=0)
    start = max(0, at - width // 3)
    if start:
        space = text.find(" ", start)
        start = space + 1 if 0 <= space < at else start
    end = start + width
    if end < len(text):
        space = text.rfind(" ", start, end)
        end = space if space > at else end
    piece = " ".join(text[start:end].split())
    return ("..." if start else "") + piece + ("..." if end < len(text) else "")


def search(store: Path, query: str, topic: str | None = None, limit: int = 10) -> list[Hit]:
    index = refresh_index(store)
    words = [w for w in query.split() if w.strip()]
    if not words:
        return []
    with closing(sqlite3.connect(index)) as connection:
        fts = bool(connection.execute("SELECT coalesce(max(fts), 0) FROM meta").fetchone()[0])
        if fts:
            match = " ".join('"' + w.replace('"', '""') + '"' for w in words)
            sql = "SELECT path, topic, kind, body FROM docs WHERE docs MATCH ?"
            params: list[object] = [match]
            if topic:
                sql += " AND topic = ?"
                params.append(topic)
            sql += " ORDER BY rank LIMIT ?"
        else:
            sql = "SELECT path, topic, kind, body FROM docs WHERE " + " AND ".join(
                "body LIKE ?" for _ in words
            )
            params = [f"%{w}%" for w in words]
            if topic:
                sql += " AND topic = ?"
                params.append(topic)
            sql += " LIMIT ?"
        params.append(limit)
        rows = connection.execute(sql, params).fetchall()
    return [Hit(path, t, kind, _snippet(body, words)) for path, t, kind, body in rows]


# --- leaderboard ----------------------------------------------------------------


@dataclass(frozen=True)
class Placing:
    model: str
    runs: int
    rankings: int  # how many reviews ranked it
    firsts: int
    score: float  # 0 = always ranked best, 1 = always ranked worst


def leaderboard(store: Path, topic: str | None = None) -> list[Placing]:
    """Which models the others ranked highest, across saved full runs.

    Each place is scaled to 0 (best) to 1 (worst) so councils of different sizes compare.
    """
    pattern = f"topics/{topic}/runs/*/rankings.json" if topic else "topics/*/runs/*/rankings.json"
    scores: dict[str, list[float]] = {}
    firsts: dict[str, int] = {}
    runs: dict[str, int] = {}
    for path in store.glob(pattern):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            responses: dict[str, str] = data["responses"]
            reviews = data["reviews"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        for model in set(responses.values()):
            runs[model] = runs.get(model, 0) + 1
        for review in reviews:
            ranking = review.get("ranking")
            if not ranking:
                continue
            size = len(ranking)
            for place, letter in enumerate(ranking):
                model = responses.get(letter)
                if model is None:
                    continue
                scores.setdefault(model, []).append(place / (size - 1) if size > 1 else 0.0)
                if place == 0:
                    firsts[model] = firsts.get(model, 0) + 1
    table = [
        Placing(
            model=model,
            runs=runs.get(model, 0),
            rankings=len(values),
            firsts=firsts.get(model, 0),
            score=round(sum(values) / len(values), 3),
        )
        for model, values in scores.items()
    ]
    return sorted(table, key=lambda p: (p.score, -p.rankings, p.model))


# --- spending -------------------------------------------------------------------


@dataclass(frozen=True)
class RunRecord:
    topic: str
    name: str
    question: str
    mode: str
    started: str  # ISO time
    cost: float
    verified: int | None  # key claims verified, for full runs that checked claims
    checked: int | None


def run_records(store: Path) -> list[RunRecord]:
    """Every saved run, newest first, from its meta.json."""
    records = []
    for meta_file in store.glob("topics/*/runs/*/meta.json"):
        try:
            meta = json.loads(meta_file.read_text(encoding="utf-8"))
            cost = float(meta["totals"]["cost_usd"])
            started = str(meta["started"])
        except (OSError, ValueError, KeyError, TypeError):
            continue
        evidence = meta.get("evidence") if isinstance(meta.get("evidence"), dict) else {}
        records.append(
            RunRecord(
                topic=meta_file.parent.parent.parent.name,
                name=meta_file.parent.name,
                question=str(meta.get("question", "")),
                mode=run_mode(meta_file.parent),
                started=started,
                cost=cost,
                verified=evidence.get("verified"),
                checked=evidence.get("claims_checked"),
            )
        )
    return sorted(records, key=lambda r: r.started, reverse=True)
