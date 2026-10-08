"""Cost estimates and spending caps."""

from __future__ import annotations

import math

from conclave.catalog import ModelInfo
from conclave.client import REASONING_ALLOWANCE, Completion
from conclave.config import Member

# A rough rule of thumb for English text. Good enough for a worst-case estimate;
# the real token counts come back from the API after each call.
CHARS_PER_TOKEN = 4

# Room the critique and synthesis prompts add around the answers they carry.
STAGE_OVERHEAD_TOKENS = 600


def estimate_tokens(text: str) -> int:
    return max(1, math.ceil(len(text) / CHARS_PER_TOKEN))


def messages_tokens(messages: list[dict[str, str]]) -> int:
    return estimate_tokens("\n".join(m["content"] for m in messages))


def critique_max_tokens(answer_tokens: int) -> int:
    """A review is shorter than an answer."""
    return min(answer_tokens, 1000)


def synthesis_max_tokens(answer_tokens: int) -> int:
    """The final page needs more room than one answer."""
    return answer_tokens + 1000


def worst_case_cost(
    members: list[Member], catalog: dict[str, ModelInfo], prompt_tokens: int, max_tokens: int
) -> float:
    """The most a stage could cost: every model reads the prompt, uses all its room for
    reasoning, and writes the longest answer allowed."""
    total = 0.0
    for member in members:
        info = catalog.get(member.model)
        if info is None:
            continue
        output = max_tokens + REASONING_ALLOWANCE
        total += prompt_tokens * info.prompt_price + output * info.completion_price
    return total


# The memory update replies with a short JSON patch.
MEMORY_MAX_TOKENS = 1500


def memory_update_cost(
    chairman: Member, catalog: dict[str, ModelInfo], listing_tokens: int, answer_tokens: int
) -> float:
    """The most the memory update could cost: it reads the memory and the chairman's page."""
    prompt = listing_tokens + STAGE_OVERHEAD_TOKENS + synthesis_max_tokens(answer_tokens)
    return worst_case_cost([chairman], catalog, prompt, MEMORY_MAX_TOKENS)


def full_run_worst_case(
    members: list[Member],
    chairman: Member,
    catalog: dict[str, ModelInfo],
    research_prompt_tokens: int,
    answer_tokens: int,
    listing_tokens: int | None = None,
) -> float:
    """The most a full run could cost, if every call writes the longest text allowed.

    `listing_tokens` is the size of the topic's memory; None means memory is not updated.
    """
    count = len(members)
    review_tokens = critique_max_tokens(answer_tokens)
    research = worst_case_cost(members, catalog, research_prompt_tokens, answer_tokens)
    critique = worst_case_cost(
        members,
        catalog,
        research_prompt_tokens + STAGE_OVERHEAD_TOKENS + (count - 1) * answer_tokens,
        review_tokens,
    )
    synthesis = worst_case_cost(
        [chairman],
        catalog,
        research_prompt_tokens + STAGE_OVERHEAD_TOKENS + count * (answer_tokens + review_tokens),
        synthesis_max_tokens(answer_tokens),
    )
    memory = (
        0.0
        if listing_tokens is None
        else memory_update_cost(chairman, catalog, listing_tokens, answer_tokens)
    )
    return research + critique + synthesis + memory


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
