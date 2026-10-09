"""The live list of models and prices from OpenRouter."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import httpx

from conclave.store import atomic_write

PER_MILLION = 1_000_000


class CatalogError(Exception):
    """The model list could not be fetched or understood."""


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    prompt_price: float | None  # US dollars per token; None when unknown
    completion_price: float | None  # US dollars per token; None when unknown
    context_length: int

    @property
    def vendor(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def prompt_per_million(self) -> float | None:
        if self.prompt_price is None:
            return None
        return self.prompt_price * PER_MILLION

    @property
    def completion_per_million(self) -> float | None:
        if self.completion_price is None:
            return None
        return self.completion_price * PER_MILLION


def _price(raw: object) -> float | None:
    """Dollars per token, or None when the figure is missing, unreadable or negative.

    Zero is a real price: a free model. A missing or negative figure cannot be
    checked against a budget, so it stays unknown and the run is refused.
    """
    if isinstance(raw, bool):
        return None
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


async def fetch_models(client: httpx.AsyncClient) -> dict[str, ModelInfo]:
    """Fetch every model OpenRouter lists, keyed by id. Needs no API key."""
    try:
        response = await client.get("/models")
        response.raise_for_status()
        entries = response.json()["data"]
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as error:
        raise CatalogError(f"could not fetch the model list from OpenRouter ({error})") from None

    models: dict[str, ModelInfo] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        pricing = entry.get("pricing") if isinstance(entry.get("pricing"), dict) else {}
        context = entry.get("context_length")
        models[entry["id"]] = ModelInfo(
            id=entry["id"],
            name=str(entry.get("name") or entry["id"]),
            prompt_price=_price(pricing.get("prompt")),
            completion_price=_price(pricing.get("completion")),
            context_length=(
                context if isinstance(context, int) and not isinstance(context, bool) else 0
            ),
        )
    return models


def search(
    models: dict[str, ModelInfo],
    text: str | None = None,
    vendor: str | None = None,
    sort: str = "name",
) -> list[ModelInfo]:
    """Filter by text (in the id or name) and vendor, then sort by name or by price."""
    found = list(models.values())
    if text:
        needle = text.lower()
        found = [m for m in found if needle in m.id.lower() or needle in m.name.lower()]
    if vendor:
        found = [m for m in found if m.vendor.lower() == vendor.lower()]
    if sort == "price":
        # Unknown prices sort last. Sorting them as zero would make them look free.
        found.sort(
            key=lambda m: (
                m.completion_price is None,
                m.completion_price if m.completion_price is not None else 0.0,
                m.prompt_price if m.prompt_price is not None else 0.0,
                m.id,
            )
        )
    else:
        found.sort(key=lambda m: m.id)
    return found


def closest(models: dict[str, ModelInfo], model_id: str, limit: int = 3) -> list[str]:
    """Ids from the same vendor that share the most leading characters with `model_id`."""
    vendor = model_id.split("/", 1)[0]
    same_vendor = [m.id for m in models.values() if m.vendor == vendor]

    def shared_prefix(candidate: str) -> int:
        count = 0
        for a, b in zip(candidate, model_id, strict=False):
            if a != b:
                break
            count += 1
        return count

    return sorted(same_vendor, key=lambda c: (-shared_prefix(c), c))[:limit]


def price_cache_path(store: Path) -> Path:
    """Where the last successful price list is kept, beside the research store."""
    return store / "model-prices.json"


def write_price_cache(path: Path, models: dict[str, ModelInfo]) -> None:
    """Save a price list. A failure leaves the previous file and does not raise."""
    payload = {
        "models": [
            {
                "id": info.id,
                "name": info.name,
                "prompt": info.prompt_price,
                "completion": info.completion_price,
                "context_length": info.context_length,
            }
            for info in models.values()
        ]
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write(path, json.dumps(payload) + "\n")
    except OSError:
        return


def read_price_cache(path: Path) -> dict[str, ModelInfo] | None:
    """The last saved price list, or None when there is none or it cannot be read."""
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["models"]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if not isinstance(entries, list):
        return None
    models: dict[str, ModelInfo] = {}
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
            continue
        context = entry.get("context_length")
        models[entry["id"]] = ModelInfo(
            id=entry["id"],
            name=str(entry.get("name") or entry["id"]),
            prompt_price=_price(entry.get("prompt")),
            completion_price=_price(entry.get("completion")),
            context_length=(
                context if isinstance(context, int) and not isinstance(context, bool) else 0
            ),
        )
    return models or None
