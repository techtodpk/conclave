import asyncio

import httpx
import pytest

from conclave.catalog import (
    CatalogError,
    ModelInfo,
    closest,
    fetch_models,
    read_price_cache,
    search,
    write_price_cache,
)
from conclave.http import new_client


def _fetch():
    async def go():
        async with new_client() as http:
            return await fetch_models(http)

    return asyncio.run(go())


def test_fetch_reads_ids_and_prices(openrouter):
    models = _fetch()

    sonnet = models["anthropic/claude-sonnet-5.5"]
    assert sonnet.vendor == "anthropic"
    assert sonnet.prompt_per_million == pytest.approx(2.0)
    assert sonnet.completion_per_million == pytest.approx(10.0)
    assert sonnet.context_length == 1_000_000
    assert len(models) == 5


def test_fetch_failure_is_a_catalog_error(openrouter):
    openrouter.models_status = 503

    with pytest.raises(CatalogError, match="could not fetch the model list"):
        _fetch()


def test_odd_entries_do_not_break_the_list(monkeypatch):
    import conclave.http

    data = [
        {"id": "a/free", "pricing": {"prompt": "-1", "completion": "abc"}},
        {"id": "b/no-pricing"},
        {"name": "no id"},
        "not a dict",
    ]
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"data": data}))
    monkeypatch.setattr(conclave.http, "TRANSPORT", transport)

    models = _fetch()

    assert set(models) == {"a/free", "b/no-pricing"}
    assert models["a/free"].prompt_price is None
    assert models["a/free"].completion_price is None
    assert models["b/no-pricing"].prompt_price is None
    assert models["b/no-pricing"].name == "b/no-pricing"


def test_a_saved_price_list_round_trips_and_keeps_unknown_prices(tmp_path):
    models = {"a/m": ModelInfo("a/m", "M", 0.1, None, 10)}
    path = tmp_path / "model-prices.json"

    write_price_cache(path, models)
    loaded = read_price_cache(path)

    assert loaded is not None
    assert loaded["a/m"].prompt_price == 0.1
    assert loaded["a/m"].completion_price is None
    assert read_price_cache(tmp_path / "missing.json") is None
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")
    assert read_price_cache(tmp_path / "broken.json") is None


def test_search_filters_and_sorts(openrouter):
    models = _fetch()

    assert [m.id for m in search(models, text="claude")] == [
        "anthropic/claude-opus-5.5",
        "anthropic/claude-sonnet-5.5",
    ]
    assert [m.id for m in search(models, vendor="Google")] == ["google/gemini-3.8-flash"]
    assert search(models, text="GPT")[0].id == "openai/gpt-6.1-sol"
    by_price = [m.id for m in search(models, sort="price")]
    assert by_price[0] == "deepseek/deepseek-v4.1-flash"
    assert by_price[-1] == "anthropic/claude-opus-5.5"
    assert search(models, text="nothing-like-this") == []


def test_closest_suggests_from_the_same_vendor(openrouter):
    models = _fetch()

    assert closest(models, "anthropic/claude-sonnet-9")[0] == "anthropic/claude-sonnet-5.5"
    assert closest(models, "unknown-vendor/model") == []
