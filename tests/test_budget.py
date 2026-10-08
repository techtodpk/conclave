import pytest

from conclave.budget import (
    cost_of,
    critique_max_tokens,
    estimate_tokens,
    full_run_worst_case,
    synthesis_max_tokens,
    worst_case_cost,
)
from conclave.catalog import ModelInfo
from conclave.client import REASONING_ALLOWANCE, Completion
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
