import json
from datetime import datetime

from conclave.store import (
    create_run,
    model_filename,
    month_spend,
    slugify,
    write_answer,
    write_meta,
    write_question,
)

WHEN = datetime(2026, 10, 7, 14, 32, 5)


def test_slugify_makes_safe_short_names():
    assert slugify("What is the best Unity DOTS pattern?") == "what-is-the-best-unity-dots-pattern"
    assert slugify("Crème brûlée: à la carte!") == "creme-brulee-a-la-carte"
    assert slugify('a/b\\c:d*e?f"g<h>i|j') == "a-b-c-d-e-f-g-h"
    assert slugify("???", fallback="question") == "question"
    assert slugify("") == "untitled"
    assert len(slugify("word " * 50)) <= 60
    assert not slugify("x" * 200).endswith("-")


def test_model_filename_has_no_path_separators():
    assert model_filename("anthropic/claude-sonnet-5.5") == "anthropic--claude-sonnet-5.5.md"
    assert model_filename("a/b:c d") == "a--b-c-d.md"


def test_create_run_builds_the_folder_layout(tmp_path):
    run = create_run(tmp_path, "Game Engines", "Is Unity DOTS ready?", WHEN)

    assert run.topic == "game-engines"
    expected = (
        tmp_path / "topics" / "game-engines" / "runs" / "2026-10-07-143205-is-unity-dots-ready"
    )
    assert run.path == expected
    assert run.answers.is_dir()


def test_a_second_run_in_the_same_second_gets_its_own_folder(tmp_path):
    first = create_run(tmp_path, "general", "Same question", WHEN)
    second = create_run(tmp_path, "general", "Same question", WHEN)

    assert first.path != second.path
    assert second.path.name.endswith("-2")


def test_writing_a_run(tmp_path):
    run = create_run(tmp_path, "", "Why?", WHEN)
    assert run.topic == "general"

    question = write_question(run, " Why? ", {"Mode": "full"})
    first = write_answer(run, "a/model", "member", "  First.  ")
    second = write_answer(run, "a/model", "member", "Second.")

    assert question.read_text(encoding="utf-8") == "# Question\n\nWhy?\n\n- Mode: full\n"
    assert first.read_text(encoding="utf-8") == "---\nmodel: a/model\nrole: member\n---\n\nFirst.\n"
    assert second.name == "a--model-2.md"


def _meta(store, topic, name, started, cost):
    folder = store / "topics" / topic / "runs" / name
    folder.mkdir(parents=True)
    (folder / "meta.json").write_text(
        json.dumps({"started": started, "totals": {"cost_usd": cost}}), encoding="utf-8"
    )


def test_month_spend_counts_only_this_month(tmp_path):
    _meta(tmp_path, "a", "one", "2026-10-01T09:00:00+05:30", 0.40)
    _meta(tmp_path, "b", "two", "2026-10-07T10:00:00+05:30", 0.25)
    _meta(tmp_path, "a", "last-month", "2026-09-30T23:00:00+05:30", 5.00)
    _meta(tmp_path, "a", "last-year", "2025-10-07T10:00:00+05:30", 7.00)
    broken = tmp_path / "topics" / "a" / "runs" / "broken"
    broken.mkdir()
    (broken / "meta.json").write_text("{not json", encoding="utf-8")
    _meta(tmp_path, "a", "no-cost", "2026-10-02T10:00:00+05:30", None)

    assert month_spend(tmp_path, WHEN) == 0.65
    assert month_spend(tmp_path / "empty", WHEN) == 0.0


def test_meta_is_readable_json(tmp_path):
    run = create_run(tmp_path, "t", "q", WHEN)

    target = write_meta(run, {"totals": {"cost_usd": 0.1}})

    assert json.loads(target.read_text(encoding="utf-8")) == {"totals": {"cost_usd": 0.1}}
