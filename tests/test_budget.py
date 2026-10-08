import pytest

from conclave.budget import (
    SEARCH_RESULT_TOKENS,
    cost_of,
    critique_max_tokens,
    estimate_tokens,
    full_run_worst_case,
    research_worst_case,
    synthesis_max_tokens,
    worst_case_cost,
)
from conclave.catalog import ModelInfo
from conclave.client import REASONING_ALLOWANCE, SEARCH_PRICE_USD, Completion
from conclave.config import Member

CHEAP = ModelInfo("a/cheap", "Cheap", 0.000001, 0.000002, 1000)
DEAR = ModelInfo("b/dear", "Dear", 0.00001, 0.00005, 1000)
CATALOG = {CHEAP.id: CHEAP, DEAR.id: DEAR}


def test_estimate_tokens_rounds_up():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_worst_case_assumes_every_member_writes_a_full_answer_after_full_reasoning():
    members = [Member("a/cheap"), Member("b/dear"), Member("c/unlisted")]

    cost = worst_case_cost(members, CATALOG, prompt_tokens=100, max_tokens=1000)

    out = 1000 + REASONING_ALLOWANCE
    assert cost == pytest.approx(100 * 0.000001 + out * 0.000002 + 100 * 0.00001 + out * 0.00005)


def test_cost_prefers_the_reported_figure():
    reported = Completion("t", 100, 50, 0.5, 1.0)
    silent = Completion("t", 100, 50, None, 1.0)

    assert cost_of(reported, CHEAP) == (0.5, "reported")
    cost, source = cost_of(silent, CHEAP)
    assert source == "estimated"
    assert cost == pytest.approx(100 * 0.000001 + 50 * 0.000002)
    assert cost_of(silent, None) == (None, "unknown")


def test_full_run_adds_critique_and_synthesis():
    members = [Member("a/cheap"), Member("b/dear")]
    chair = Member("b/dear")

    research_only = worst_case_cost(members, CATALOG, 100, 1000)
    whole = full_run_worst_case(members, chair, CATALOG, 100, 1000)

    critique = worst_case_cost(members, CATALOG, 100 + 600 + 1000, critique_max_tokens(1000))
    synthesis = worst_case_cost([chair], CATALOG, 100 + 600 + 2 * 2000, synthesis_max_tokens(1000))
    assert whole == pytest.approx(research_only + critique + synthesis)


def test_stage_lengths():
    assert critique_max_tokens(1500) == 1000
    assert critique_max_tokens(400) == 400
    assert synthesis_max_tokens(1500) == 2500


def test_search_raises_the_research_ceiling_by_reading_results_and_paying_per_search():
    members = [Member("a/cheap")]
    plain = research_worst_case(members, CATALOG, 100, 1000, searches=0)
    searched = research_worst_case(members, CATALOG, 100, 1000, searches=3)

    results = 10 * SEARCH_RESULT_TOKENS  # capped at 10 results per answer
    extra_prompt = 3 * 100 + 3 * results
    assert searched - plain == pytest.approx(extra_prompt * 0.000001 + 3 * SEARCH_PRICE_USD)


def test_full_run_ceiling_includes_checking_only_with_search():
    members = [Member("a/cheap"), Member("b/dear")]
    chair = Member("b/dear")
    without = full_run_worst_case(members, chair, CATALOG, 100, 500, None, 0, chair, 8)
    no_checker = full_run_worst_case(members, chair, CATALOG, 100, 500, None, 2, None, 8)
    full = full_run_worst_case(members, chair, CATALOG, 100, 500, None, 2, chair, 8)

    assert without < no_checker < full


def test_estimated_cost_adds_search_fees():
    done = Completion("t", 100, 50, None, 1.0, searches=2)

    cost, source = cost_of(done, CHEAP)

    assert source == "estimated"
    assert cost == pytest.approx(100 * 0.000001 + 50 * 0.000002 + 2 * SEARCH_PRICE_USD)
