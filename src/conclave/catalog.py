"""The live list of models and prices from OpenRouter."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

PER_MILLION = 1_000_000


class CatalogError(Exception):
    """The model list could not be fetched or understood."""


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    prompt_price: float  # US dollars per token
    completion_price: float  # US dollars per token
    context_length: int

    @property
    def vendor(self) -> str:
        return self.id.split("/", 1)[0]

    @property
    def prompt_per_million(self) -> float:
        return self.prompt_price * PER_MILLION

    @property
    def completion_per_million(self) -> float:
        return self.completion_price * PER_MILLION


def _price(raw: object) -> float:
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


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
            context_length=context if isinstance(context, int) else 0,
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
        found.sort(key=lambda m: (m.completion_price, m.prompt_price, m.id))
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
