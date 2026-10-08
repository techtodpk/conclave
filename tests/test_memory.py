import json
from datetime import date

import pytest

from conclave.memory import (
    MemoryFileError,
    TopicMemory,
    add_note,
    apply_patch,
    build_recall,
    load_memory,
    parse_patch,
    read_notes,
    save_memory,
)

TODAY = date(2026, 10, 8)
LATER = date(2026, 10, 9)


def _memory_with_claims() -> TopicMemory:
    memory = TopicMemory("unity")
    apply_patch(
        memory,
        {
            "add": [
                {
                    "text": "DOTS is production ready for simulation.",
                    "label": "agreed but unchecked",
                },
                {"text": "Burst speeds up maths code.", "label": "agreed but unchecked"},
            ],
            "open_disputes": [{"text": "Whether DOTS suits small teams."}],
        },
        "run-1",
        TODAY,
    )
    return memory


def test_add_follows_the_entry_rule():
    memory = TopicMemory("unity")

    changes = apply_patch(
        memory,
        {
            "add": [
                {"text": "Agreed claim.", "label": "agreed but unchecked"},
                {"text": "Lonely claim.", "label": "single model"},
                {"text": "Contested claim.", "label": "disputed"},
                {"text": "No label."},
                {"text": "  ", "label": "agreed but unchecked"},
            ]
        },
        "run-1",
        TODAY,
    )

    assert [(c.id, c.text) for c in memory.claims] == [("C1", "Agreed claim.")]
    assert len(changes.added) == 1
    assert len(changes.skipped) == 3


def test_duplicates_are_not_added_again():
    memory = _memory_with_claims()

    changes = apply_patch(
        memory,
        {"add": [{"text": "burst speeds up MATHS code", "label": "agreed but unchecked"}]},
        "run-2",
        LATER,
    )

    assert changes.empty
    assert "already in memory" in changes.skipped[0]


def test_change_keeps_history_and_needs_an_entry_label():
    memory = _memory_with_claims()

    changes = apply_patch(
        memory,
        {
            "change": [
                {
                    "id": "C1",
                    "text": "DOTS suits large simulations.",
                    "label": "agreed but unchecked",
                    "reason": "Narrower.",
                },
                {"id": "C2", "text": "Contested.", "label": "disputed"},
                {"id": "C9", "text": "No such claim.", "label": "agreed but unchecked"},
            ]
        },
        "run-2",
        LATER,
    )

    claim = memory.claim("C1")
    assert claim.text == "DOTS suits large simulations."
    assert claim.updated == "2026-10-09" and claim.updated_run == "run-2"
    assert claim.history == [
        {
            "date": "2026-10-09",
            "run": "run-2",
            "text": "DOTS is production ready for simulation.",
            "reason": "Narrower.",
        }
    ]
    assert memory.claim("C2").text == "Burst speeds up maths code."
    assert len(changes.changed) == 1 and len(changes.skipped) == 2


def test_retire_needs_a_reason_and_keeps_the_claim():
    memory = _memory_with_claims()

    changes = apply_patch(
        memory,
        {"retire": [{"id": "C1", "reason": "Superseded."}, {"id": "C2"}]},
        "run-2",
        LATER,
    )

    assert [c.id for c in memory.active_claims] == ["C2"]
    assert memory.claim("C1").retired_reason == "Superseded."
    assert len(changes.retired) == 1
    assert "no reason" in changes.skipped[0]
    assert memory.next_claim_id() == "C3"  # ids are never reused


def test_disputes_open_and_resolve():
    memory = _memory_with_claims()

    changes = apply_patch(
        memory,
        {
            "open_disputes": [
                {"text": "Whether DOTS suits small teams."},
                {"text": "Netcode maturity."},
            ],
            "resolve_disputes": [{"id": "D1", "resolution": "Fine for small teams with care."}],
        },
        "run-2",
        LATER,
    )

    assert [d.id for d in memory.open_disputes] == ["D2"]
    assert memory.dispute("D1").resolution == "Fine for small teams with care."
    assert [d.text for d in changes.opened] == ["Netcode maturity."]
    assert changes.lines()[-1].startswith("- Resolved dispute D1")


@pytest.mark.parametrize(
    "reply",
    [
        '```json\n{"add": [{"text": "X.", "label": "agreed but unchecked"}]}\n```',
        'Here you go: {"add": [{"text": "X.", "label": "agreed but unchecked"}]} Done.',
        '{"add": [{"text": "X.", "label": "agreed but unchecked"}], "retire": "oops"}',
    ],
)
def test_parse_patch_finds_the_json(reply):
    patch = parse_patch(reply)

    assert patch["add"] == [{"text": "X.", "label": "agreed but unchecked"}]
    assert patch["retire"] == [] or isinstance(patch["retire"], list)


@pytest.mark.parametrize(
    "reply", ["No changes needed.", '{"something": 1}', "```json\n{broken\n```"]
)
def test_parse_patch_rejects_what_is_not_a_patch(reply):
    assert parse_patch(reply) is None


def test_save_writes_json_summary_and_disputes(tmp_path):
    memory = _memory_with_claims()
    apply_patch(memory, {"retire": [{"id": "C2", "reason": "Wrong."}]}, "run-2", LATER)

    save_memory(tmp_path, memory)

    assert load_memory(tmp_path, "unity").claim("C2").retired == "2026-10-09"
    summary = (tmp_path / "summary.md").read_text(encoding="utf-8")
    assert "- **C1** DOTS is production ready for simulation. [agreed but unchecked]" in summary
    assert "~~**C2** Burst speeds up maths code.~~ *Retired 2026-10-09: Wrong.*" in summary
    assert "**D1** Whether DOTS suits small teams." in (tmp_path / "disputes.md").read_text(
        encoding="utf-8"
    )


def test_missing_memory_is_empty_and_broken_memory_is_an_error(tmp_path):
    assert load_memory(tmp_path, "t").claims == []

    (tmp_path / "memory.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(MemoryFileError, match="memory.json"):
        load_memory(tmp_path, "t")


def test_notes_are_appended_never_rewritten(tmp_path):
    add_note(tmp_path, "unity", "  Prefer URP. ", TODAY)
    add_note(tmp_path, "unity", "We target mobile.", LATER)

    text = read_notes(tmp_path)
    assert text.startswith("# unity: notes")
    assert text.endswith("- 2026-10-08: Prefer URP.\n- 2026-10-09: We target mobile.")


def test_recall_puts_notes_first_and_skips_retired_and_resolved(tmp_path):
    memory = _memory_with_claims()
    apply_patch(
        memory,
        {
            "retire": [{"id": "C2", "reason": "Wrong."}],
            "resolve_disputes": [{"id": "D1", "resolution": "Settled."}],
        },
        "run-2",
        LATER,
    )
    add_note(tmp_path, "unity", "We target mobile.", TODAY)

    recall = build_recall(tmp_path, memory)

    assert recall.text.index("We target mobile.") < recall.text.index("C1:")
    assert "C2" not in recall.text and "D1" not in recall.text
    assert (recall.claims, recall.disputes, recall.has_notes, recall.truncated) == (
        1,
        0,
        True,
        False,
    )


def test_empty_topic_recalls_nothing(tmp_path):
    recall = build_recall(tmp_path, TopicMemory("new"))

    assert recall.text == "" and recall.claims == 0


def test_long_memory_is_cut_short(tmp_path):
    memory = TopicMemory("big")
    apply_patch(
        memory,
        {
            "add": [
                {"text": f"Claim number {i} " + "x" * 200, "label": "agreed but unchecked"}
                for i in range(100)
            ]
        },
        "run-1",
        TODAY,
    )

    recall = build_recall(tmp_path, memory)

    assert recall.truncated
    assert len(recall.text) < 12_100
    assert recall.text.endswith("(Earlier research cut short.)")
    json.dumps(recall.text)
