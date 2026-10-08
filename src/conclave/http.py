"""One place that creates HTTP clients, so tests can swap the transport."""

from __future__ import annotations

import httpx

API_BASE = "https://openrouter.ai/api/v1"
TIMEOUT_SECONDS = 180.0

# Tests set this to an httpx.MockTransport. It stays None in normal use.
TRANSPORT: httpx.AsyncBaseTransport | None = None


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url=API_BASE,
        timeout=httpx.Timeout(TIMEOUT_SECONDS, connect=20.0),
        transport=TRANSPORT,
        headers={"User-Agent": "conclave"},
    )
