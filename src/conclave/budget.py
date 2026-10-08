"""Cost estimates and spending caps."""

from __future__ import annotations

import math

from conclave.catalog import ModelInfo
from conclave.client import Completion
from conclave.config import Member

# A rough rule of thumb for English text. Good enough for a worst-case estimate;
# the real token counts come back from the API after the call.
CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def worst_case_cost(
    members: list[Member], catalog: dict[str, ModelInfo], prompt_text: str, max_tokens: int
) -> float:
    """The most this stage could cost: every member reads the prompt and writes a full answer."""
    prompt_tokens = estimate_tokens(prompt_text)
    total = 0.0
    for member in members:
        info = catalog.get(member.model)
        if info is None:
            continue
        total += prompt_tokens * info.prompt_price + max_tokens * info.completion_price
    return total


def cost_of(completion: Completion, info: ModelInfo | None) -> tuple[float | None, str]:
    """What a call cost, and where the figure came from: reported, estimated or unknown."""
    if completion.cost_usd is not None:
        return completion.cost_usd, "reported"
    if info is not None:
        computed = (
            completion.prompt_tokens * info.prompt_price
            + completion.completion_tokens * info.completion_price
        )
        return computed, "estimated"
    return None, "unknown"
