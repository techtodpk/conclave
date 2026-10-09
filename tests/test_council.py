from dataclasses import replace

from conclave.client import Completion
from conclave.config import Member
from conclave.council import (
    Labeled,
    Review,
    Seat,
    SeatResult,
    final_page,
    label_answers,
    parse_ranking,
    standings,
)


def _done(text: str = "text") -> Completion:
    return Completion(text, 10, 10, 0.001, 1.0)


def _result(model: str, ok: bool = True) -> SeatResult:
    seat = Seat(Member(model), "member")
    return SeatResult(seat, _done(f"from {model}")) if ok else SeatResult(seat, error="x")


ANSWERS = [Labeled("A", "a/one", "one"), Labeled("B", "b/two", "two"), Labeled("C", "c/three", "3")]


def test_letters_go_to_successful_answers_in_order():
    labeled = label_answers([_result("a/one"), _result("b/two", ok=False), _result("c/three")])

    assert [(x.letter, x.model) for x in labeled] == [("A", "a/one"), ("B", "c/three")]


def test_parse_ranking_reads_the_last_ranking_section():
    text = (
        "## Response B\n\nResponse C is cited here.\n\n## Ranking\n\n1. Response C\n2. Response B\n"
    )

    assert parse_ranking(text, ["B", "C"]) == ("C", "B")


def test_parse_ranking_tolerates_formatting():
    text = "### RANKING:\n\n1) **Response b**\n2) response A — weaker"

    assert parse_ranking(text, ["A", "B"]) == ("B", "A")


def test_parse_ranking_refuses_to_guess():
    assert parse_ranking("1. Response A\n2. Response B", ["A", "B"]) is None  # no heading
    assert parse_ranking("## Ranking\n1. Response A", ["A", "B"]) is None  # one missing
    assert parse_ranking("## Ranking\n1. Response A\n2. Response A", ["A", "B"]) is None
    assert parse_ranking("## Ranking\n1. Response A\n2. Response D", ["A", "B"]) is None


def _review(letter: str, ranking: tuple[str, ...] | None, ok: bool = True) -> Review:
    reviewed = tuple(a.letter for a in ANSWERS if a.letter != letter)
    return Review(_result("x/y", ok), letter, reviewed, ranking)


def test_standings_average_positions_best_first():
    reviews = [
        _review("A", ("C", "B")),
        _review("B", ("C", "A")),
        _review("C", ("A", "B")),
    ]

    table = standings(ANSWERS, reviews)

    assert [(s.letter, s.average_position, s.votes) for s in table] == [
        ("C", 1.0, 2),
        ("A", 1.5, 2),
        ("B", 2.0, 2),
    ]


def test_unranked_answers_go_last():
    table = standings(ANSWERS, [_review("A", ("B", "C")), _review("B", None), _review("C", None)])

    assert [(s.letter, s.average_position) for s in table] == [("B", 1.0), ("C", 2.0), ("A", None)]


def test_final_page_names_models_and_counts_readable_rankings():
    reviews = [_review("A", ("C", "B")), _review("B", None), _review("C", None, ok=False)]
    table = standings(ANSWERS, reviews)

    page = final_page(
        " Why? ", "## Answer\n\nBecause.", "2026-10-08 20:58", "balanced", "c/three", table, reviews
    )

    assert page.startswith("# Why?\n\n*Conclave full run, 2026-10-08 20:58, profile 'balanced'.")
    assert "## Answer\n\nBecause." in page
    assert "The chairman, `c/three`," in page
    assert "| C | `c/three` | 1.0 (1 review) |" in page
    assert "| A | `a/one` | not ranked |" in page
    assert "Readable rankings: 1 of 3." in page


def test_an_answer_is_unsourced_only_if_search_worked_and_nothing_was_cited():
    from conclave.client import Completion, Source
    from conclave.council import _unsourced

    base = Completion("text", 1, 1, 0.0, 1.0)
    assert _unsourced(base)
    assert _unsourced(replace(base, searches=None))
    assert not _unsourced(replace(base, searches=2))
    assert not _unsourced(replace(base, sources=(Source("https://a.example"),)))
    assert not _unsourced(replace(base, search_failed="HTTP 504"))
