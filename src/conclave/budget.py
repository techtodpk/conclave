"""Cost estimates and spending caps."""

from __future__ import annotations

import math

from conclave.catalog import ModelInfo
from conclave.client import (
    MAX_RESULTS_PER_ANSWER,
    REASONING_ALLOWANCE,
    RESULTS_PER_SEARCH,
    SEARCH_PRICE_USD,
    Completion,
)
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
) -> float | None:
    """The most a stage could cost: every model reads the prompt, uses all its room for
    reasoning, and writes the longest answer allowed.

    None when any member's price is missing. That is not zero: a missing price cannot
    be checked, and the caller must refuse the stage rather than treat it as free.
    """
    total = 0.0
    for member in members:
        info = catalog.get(member.model)
        if info is None or info.prompt_price is None or info.completion_price is None:
            return None
        output = max_tokens + REASONING_ALLOWANCE
        total += prompt_tokens * info.prompt_price + output * info.completion_price
    return total


# The memory update replies with a short JSON patch.
MEMORY_MAX_TOKENS = 1500


def memory_update_cost(
    chairman: Member, catalog: dict[str, ModelInfo], listing_tokens: int, answer_tokens: int
) -> float | None:
    """The most the memory update could cost: it reads the memory and the chairman's page."""
    prompt = listing_tokens + STAGE_OVERHEAD_TOKENS + synthesis_max_tokens(answer_tokens)
    return worst_case_cost([chairman], catalog, prompt, MEMORY_MAX_TOKENS)


# An Exa search result reaches the model as an excerpt of 2,000 to 4,000 characters.
SEARCH_RESULT_TOKENS = 800

# Claim checking: the checker picks the key claims, then tests each against its sources.
EXTRACT_MAX_TOKENS = 1200
SOURCES_PER_CLAIM = 2
PASSAGE_CHARS = 2500  # the part of each source page the checker reads for one claim
CLAIM_TOKENS = 80  # one claim and its labels in a prompt


def check_max_tokens(claims: int) -> int:
    """The checker writes a short verdict, a quote and a note for each claim."""
    return 300 + 150 * claims


def check_prompt_tokens(claims: int) -> int:
    passages = claims * SOURCES_PER_CLAIM * math.ceil(PASSAGE_CHARS / CHARS_PER_TOKEN)
    return STAGE_OVERHEAD_TOKENS + claims * CLAIM_TOKENS + passages


def research_worst_case(
    members: list[Member],
    catalog: dict[str, ModelInfo],
    prompt_tokens: int,
    answer_tokens: int,
    searches: int = 0,
) -> float | None:
    """The most the Research stage could cost, searches included.

    After each search the model reads the whole conversation again, so the question is
    billed up to `searches` + 1 times, and the search results pile up as it goes.
    None when a member's price is unknown.
    """
    if searches <= 0:
        return worst_case_cost(members, catalog, prompt_tokens, answer_tokens)
    results = min(searches * RESULTS_PER_SEARCH, MAX_RESULTS_PER_ANSWER) * SEARCH_RESULT_TOKENS
    prompt = (searches + 1) * prompt_tokens + searches * results
    fees = len(members) * searches * SEARCH_PRICE_USD
    base = worst_case_cost(members, catalog, prompt, answer_tokens)
    if base is None:
        return None
    return base + fees


def verify_worst_case(
    checker: Member,
    catalog: dict[str, ModelInfo],
    extract_prompt_tokens: int,
    claims: int,
) -> float | None:
    """The most claim checking could cost: picking the claims, then checking them.

    None when the checker's price is unknown.
    """
    if claims <= 0:
        return 0.0
    extract = worst_case_cost([checker], catalog, extract_prompt_tokens, EXTRACT_MAX_TOKENS)
    check = worst_case_cost(
        [checker], catalog, check_prompt_tokens(claims), check_max_tokens(claims)
    )
    if extract is None or check is None:
        return None
    return extract + check


def full_run_worst_case(
    members: list[Member],
    chairman: Member,
    catalog: dict[str, ModelInfo],
    research_prompt_tokens: int,
    answer_tokens: int,
    listing_tokens: int | None = None,
    searches: int = 0,
    checker: Member | None = None,
    claims: int = 0,
) -> float | None:
    """The most a full run could cost, if every call writes the longest text allowed.

    None when any part of the run cannot be priced.

    `listing_tokens` is the size of the topic's memory; None means memory is not updated.
    `searches` is each member's search limit, 0 for no web search. Claims are checked
    only when there are searches to check them against and a checker.
    """
    count = len(members)
    review_tokens = critique_max_tokens(answer_tokens)
    research = research_worst_case(
        members, catalog, research_prompt_tokens, answer_tokens, searches
    )
    critique = worst_case_cost(
        members,
        catalog,
        research_prompt_tokens + STAGE_OVERHEAD_TOKENS + (count - 1) * answer_tokens,
        review_tokens,
    )
    discussion = (
        research_prompt_tokens + STAGE_OVERHEAD_TOKENS + count * (answer_tokens + review_tokens)
    )
    checked = claims if searches > 0 and checker is not None else 0
    verify = 0.0 if checker is None else verify_worst_case(checker, catalog, discussion, checked)
    synthesis = worst_case_cost(
        [chairman],
        catalog,
        discussion + checked * (CLAIM_TOKENS + 200),
        synthesis_max_tokens(answer_tokens),
    )
    memory = (
        0.0
        if listing_tokens is None
        else memory_update_cost(chairman, catalog, listing_tokens, answer_tokens)
    )
    parts = (research, critique, verify, synthesis, memory)
    if any(part is None for part in parts):
        return None
    return sum(parts)


def cost_of(completion: Completion, info: ModelInfo | None) -> tuple[float | None, str]:
    """What a call cost, and where the figure came from: reported, estimated or unknown."""
    if completion.cost_usd is not None:
        return completion.cost_usd, "reported"
    if info is not None and info.prompt_price is not None and info.completion_price is not None:
        computed = (
            completion.prompt_tokens * info.prompt_price
            + completion.completion_tokens * info.completion_price
            + (completion.searches or 0) * SEARCH_PRICE_USD
        )
        return computed, "estimated"
    return None, "unknown"
