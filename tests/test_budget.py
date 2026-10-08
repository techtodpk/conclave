import pytest

from conclave.budget import cost_of, estimate_tokens, worst_case_cost
from conclave.catalog import ModelInfo
from conclave.client import Completion
from conclave.config import Member

CHEAP = ModelInfo("a/cheap", "Cheap", 0.000001, 0.000002, 1000)
DEAR = ModelInfo("b/dear", "Dear", 0.00001, 0.00005, 1000)
CATALOG = {CHEAP.id: CHEAP, DEAR.id: DEAR}


def test_estimate_tokens_rounds_up():
    assert estimate_tokens("") == 1
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("abcde") == 2


def test_worst_case_assumes_every_member_writes_a_full_answer():
    members = [Member("a/cheap"), Member("b/dear"), Member("c/unlisted")]

    cost = worst_case_cost(members, CATALOG, "x" * 400, max_tokens=1000)

    assert cost == pytest.approx(100 * 0.000001 + 1000 * 0.000002 + 100 * 0.00001 + 1000 * 0.00005)


def test_cost_prefers_the_reported_figure():
    reported = Completion("t", 100, 50, 0.5, 1.0)
    silent = Completion("t", 100, 50, None, 1.0)

    assert cost_of(reported, CHEAP) == (0.5, "reported")
    cost, source = cost_of(silent, CHEAP)
    assert source == "estimated"
    assert cost == pytest.approx(100 * 0.000001 + 50 * 0.000002)
    assert cost_of(silent, None) == (None, "unknown")
