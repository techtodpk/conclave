"""Public model rankings beside the council's own leaderboard (decision 0015).

Two published sources, each fetched at most once a day and cached in the research store:

- LMArena's text leaderboard: people's votes between two anonymous answers, as a rating.
  Public dataset on Hugging Face, CC BY 4.0. No key needed.
- Artificial Analysis: its Intelligence Index, from its own benchmark runs. Free API with
  the user's own key; attribution required.

Each source names models its own way, so a model is matched by company and name, allowing
a reasoning-level ending such as "-high" or "-max"; model_names.toml covers the rest.
"""

from __future__ import annotations

import json
import os
import re
import time
import tomllib
from dataclasses import asdict, dataclass, field
from importlib import resources
from pathlib import Path

import httpx

from conclave.keys import key_locations, read_env_file

CACHE_SECONDS = 24 * 60 * 60
AA_KEY_NAME = "ARTIFICIAL_ANALYSIS_API_KEY"

LMARENA_ROWS = "https://datasets-server.huggingface.co/rows"
LMARENA_FILTER = "https://datasets-server.huggingface.co/filter"
LMARENA_DATASET = "lmarena-ai/leaderboard-dataset"
AA_MODELS = "https://artificialanalysis.ai/api/v2/data/llms/models"


@dataclass(frozen=True)
class SourceInfo:
    key: str
    name: str
    url: str  # where people can see the ranking
    credit: str  # the attribution line shown with every use
    measure: str  # what the number means


LMARENA = SourceInfo(
    "lmarena",
    "LMArena",
    "https://lmarena.ai/leaderboard/text",
    "LMArena text leaderboard, CC BY 4.0 (lmarena.ai)",
    "Rating from people's votes between two anonymous answers; higher is better",
)
ARTIFICIAL_ANALYSIS = SourceInfo(
    "artificial_analysis",
    "Artificial Analysis",
    "https://artificialanalysis.ai/leaderboards/models",
    "Data from Artificial Analysis (artificialanalysis.ai)",
    "Intelligence Index from Artificial Analysis' own evaluations; higher is better",
)
SOURCES = (LMARENA, ARTIFICIAL_ANALYSIS)


class RankingError(Exception):
    """A source could not be read. The message says why, in plain words."""


@dataclass
class Entry:
    name: str  # the source's own name for the model
    company: str  # the source's own name for the company, lowercased
    value: float
    rank: int | None = None


@dataclass
class Board:
    """One source's ranking, as fetched."""

    source: str  # SourceInfo.key
    published: str  # the source's own date for this ranking, or the date fetched
    fetched_at: float  # seconds since the epoch
    entries: list[Entry] = field(default_factory=list)

    @property
    def info(self) -> SourceInfo:
        return next(s for s in SOURCES if s.key == self.source)


# --- matching OpenRouter ids to each source's names --------------------------------------

# OpenRouter's company prefix, where a source spells the company differently.
COMPANIES = {
    "x-ai": "xai",
    "qwen": "alibaba",
    "moonshotai": "moonshot",
    "mistralai": "mistral",
    "z-ai": "zai",
    "meta-llama": "meta",
    "bytedance-seed": "bytedance",
    "stepfun-ai": "stepfun",
    "microsoft": "microsoft",
}

# Endings a source adds for a model's reasoning level or build date; the model is the same.
VARIANT = re.compile(
    r"^(?:-(?:low|medium|high|xhigh|max|minimal|thinking|reasoning|non-reasoning|\d{8}))+$"
)


def _plain(name: str) -> str:
    """A model name compared loosely: lower case, dots and spaces as dashes, no brackets."""
    name = re.sub(r"[()\[\]]", "", name.lower().strip())
    return re.sub(r"[\s._/]+", "-", name)


def _company(model_id: str) -> str:
    vendor = model_id.split("/", 1)[0].lstrip("~").lower()
    return COMPANIES.get(vendor, vendor)


def load_overrides() -> dict[str, dict[str, str]]:
    """model_names.toml: per source, OpenRouter id -> the source's exact name."""
    text = resources.files("conclave").joinpath("model_names.toml").read_text(encoding="utf-8")
    data = tomllib.loads(text)
    return {source: dict(names) for source, names in data.items() if isinstance(names, dict)}


def match(
    model_id: str, board: Board, overrides: dict[str, dict[str, str]] | None = None
) -> Entry | None:
    """The source's entry for an OpenRouter model id, or None.

    Same company and same name, allowing a reasoning-level or date ending. When several
    variants match, the best-rated one is used, and its name is shown with it.
    """
    wanted = (overrides or {}).get(board.source, {}).get(model_id.split(":", 1)[0])
    if wanted:
        return next((e for e in board.entries if e.name == wanted), None)
    base = _plain(model_id.split(":", 1)[0].split("/", 1)[-1])
    company = _company(model_id)
    found = [
        e
        for e in board.entries
        if (not e.company or e.company == company) and _same_model(base, e.name)
    ]
    return max(found, key=lambda e: e.value) if found else None


def _same_model(base: str, name: str) -> bool:
    name = _plain(name)
    return name == base or (name.startswith(base) and bool(VARIANT.match(name[len(base) :])))


# --- fetching ------------------------------------------------------------------------------


def _cache(store: Path, source: str) -> Path:
    return store / ".cache" / "rankings" / f"{source}.json"


def _read_cache(store: Path, source: str) -> Board | None:
    try:
        data = json.loads(_cache(store, source).read_text(encoding="utf-8"))
        entries = [Entry(**e) for e in data.pop("entries")]
        return Board(**data, entries=entries)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def _write_cache(store: Path, board: Board) -> None:
    path = _cache(store, board.source)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(board)), encoding="utf-8")


def aa_key(config_path: Path) -> str | None:
    """The Artificial Analysis key, from the environment or a .env file. Never printed."""
    value = os.environ.get(AA_KEY_NAME, "").strip()
    if value:
        return value
    for location in key_locations(config_path):
        value = read_env_file(location).get(AA_KEY_NAME, "").strip()
        if value:
            return value
    return None


async def fetch_lmarena(http: httpx.AsyncClient) -> Board:
    """LMArena's latest overall text leaderboard."""
    rows: list[dict] = []
    offset = 0
    while True:
        params = {
            "dataset": LMARENA_DATASET,
            "config": "text",
            "split": "latest",
            "where": "\"category\"='overall'",
            "offset": offset,
            "length": 100,
        }
        try:
            response = await http.get(LMARENA_FILTER, params=params)
        except httpx.HTTPError as error:
            raise RankingError(f"LMArena could not be reached ({type(error).__name__})") from None
        if response.status_code != 200:
            raise RankingError(f"LMArena's data returned HTTP {response.status_code}")
        page = response.json()
        rows += [item.get("row", {}) for item in page.get("rows", [])]
        offset += 100
        if not page.get("rows") or offset >= int(page.get("num_rows_total") or 0) or offset >= 3000:
            break
    entries = []
    published = ""
    for row in rows:
        try:
            entries.append(
                Entry(
                    name=str(row["model_name"]),
                    company=str(row.get("organization") or "").lower(),
                    value=round(float(row["rating"]), 1),
                    rank=int(row["rank"]) if row.get("rank") is not None else None,
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
        published = max(published, str(row.get("leaderboard_publish_date") or ""))
    if not entries:
        raise RankingError("LMArena's data had no overall text leaderboard in it")
    return Board(LMARENA.key, published or time.strftime("%Y-%m-%d"), time.time(), entries)


async def fetch_artificial_analysis(http: httpx.AsyncClient, key: str) -> Board:
    """Artificial Analysis' Intelligence Index for every model it has evaluated."""
    try:
        response = await http.get(AA_MODELS, headers={"x-api-key": key})
    except httpx.HTTPError as error:
        raise RankingError(
            f"Artificial Analysis could not be reached ({type(error).__name__})"
        ) from None
    if response.status_code in (401, 403):
        raise RankingError(
            "Artificial Analysis did not accept the key. Check ARTIFICIAL_ANALYSIS_API_KEY "
            "in your .env file against the key shown at artificialanalysis.ai."
        )
    if response.status_code != 200:
        raise RankingError(f"Artificial Analysis returned HTTP {response.status_code}")
    try:
        models = response.json().get("data") or []
    except ValueError:
        raise RankingError("Artificial Analysis returned something that is not JSON") from None
    entries = []
    for model in models:
        if not isinstance(model, dict):
            continue
        score = (model.get("evaluations") or {}).get("artificial_analysis_intelligence_index")
        if not isinstance(score, int | float) or isinstance(score, bool):
            continue
        creator = model.get("model_creator") or {}
        entries.append(
            Entry(
                name=str(model.get("slug") or model.get("name") or ""),
                company=str(creator.get("slug") or "").lower(),
                value=round(float(score), 1),
            )
        )
    entries.sort(key=lambda e: -e.value)
    for place, entry in enumerate(entries, 1):
        entry.rank = place
    if not entries:
        raise RankingError("Artificial Analysis returned no models with an Intelligence Index")
    return Board(ARTIFICIAL_ANALYSIS.key, time.strftime("%Y-%m-%d"), time.time(), entries)


@dataclass
class Fetched:
    boards: list[Board]
    problems: list[str]  # one plain sentence per source that could not be read
    missing_key: bool  # Artificial Analysis skipped for want of a key


async def fetch_boards(
    http: httpx.AsyncClient, store: Path, config_path: Path, refresh: bool = False
) -> Fetched:
    """Every source, from the cache when it is under a day old. A failed source keeps the
    last cached copy, if there is one, and says so."""
    boards: list[Board] = []
    problems: list[str] = []
    key = aa_key(config_path)
    for info in SOURCES:
        if info is ARTIFICIAL_ANALYSIS and not key:
            continue
        cached = _read_cache(store, info.key)
        if cached and not refresh and time.time() - cached.fetched_at < CACHE_SECONDS:
            boards.append(cached)
            continue
        try:
            if info is LMARENA:
                board = await fetch_lmarena(http)
            else:
                board = await fetch_artificial_analysis(http, key or "")
        except RankingError as error:
            reason = str(error).rstrip(".")
            if cached:
                boards.append(cached)
                problems.append(f"{reason}; showing the copy from {cached.published}.")
            else:
                problems.append(f"{reason}.")
            continue
        _write_cache(store, board)
        boards.append(board)
    return Fetched(boards, problems, missing_key=key is None)


# --- the table --------------------------------------------------------------------------


@dataclass
class Cell:
    value: float
    rank: int | None
    name: str  # the source's name for the matched model


@dataclass
class Row:
    model: str  # OpenRouter id
    price_in: float | None  # US dollars per million input tokens, from OpenRouter
    price_out: float | None
    cells: dict[str, Cell | None]  # source key -> its figure, or None if not ranked there
    council: float | None  # the personal leaderboard score: 0 best, 1 worst
    council_rankings: int  # how many reviews it is based on
    yours: bool  # in one of your councils


def table(
    boards: list[Board],
    yours: list[str],
    personal: dict[str, tuple[float, int]],
    catalog: dict,
    top: int = 10,
) -> list[Row]:
    """One row per model: your councils' models, models on your leaderboard, and the
    `top` best of each source among models OpenRouter offers."""
    overrides = load_overrides()
    ids = list(dict.fromkeys([*yours, *personal]))
    if top > 0:
        offered = [i for i in catalog if ":" not in i]
        for board in boards:
            ranked = []
            for model_id in offered:
                entry = match(model_id, board, overrides)
                if entry is not None:
                    ranked.append((entry.value, model_id))
            ranked.sort(reverse=True)
            ids += [model_id for _, model_id in ranked[:top] if model_id not in ids]
    rows = []
    for model_id in ids:
        info = catalog.get(model_id)
        cells = {}
        for board in boards:
            entry = match(model_id, board, overrides)
            cells[board.source] = Cell(entry.value, entry.rank, entry.name) if entry else None
        score, count = personal.get(model_id, (None, 0))
        rows.append(
            Row(
                model=model_id,
                price_in=round(info.prompt_per_million, 4) if info else None,
                price_out=round(info.completion_per_million, 4) if info else None,
                cells=cells,
                council=score,
                council_rankings=count,
                yours=model_id in yours,
            )
        )
    first = boards[0].source if boards else None

    def order(row: Row) -> tuple:
        cell = row.cells.get(first) if first else None
        return (cell is None, -(cell.value if cell else 0), row.model)

    return sorted(rows, key=order)


@dataclass
class View:
    """Everything the command line and the app show."""

    boards: list[Board]
    rows: list[Row]
    problems: list[str]
    missing_key: bool


async def view(settings, config_path: Path, refresh: bool = False, top: int = 10) -> View:
    """Fetch the sources and build the table for the user's councils and leaderboard."""
    from conclave import library
    from conclave.catalog import CatalogError, fetch_models
    from conclave.http import new_client

    yours = list(
        dict.fromkeys(
            m.model for p in settings.profiles.values() for m in [*p.members, p.chairman, p.checker]
        )
    )
    personal = {p.model: (p.score, p.rankings) for p in library.leaderboard(settings.store_path)}
    async with new_client() as http:
        fetched = await fetch_boards(http, settings.store_path, config_path, refresh)
        try:
            catalog = await fetch_models(http)
        except CatalogError as error:
            catalog = {}
            fetched.problems.append(f"OpenRouter's prices could not be read ({error}).")
    rows = table(fetched.boards, yours, personal, catalog, top)
    return View(fetched.boards, rows, fetched.problems, fetched.missing_key)
