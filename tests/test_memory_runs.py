import json
import shutil
import subprocess

import pytest
from typer.testing import CliRunner

from conclave.cli import app
from conclave.gitstore import commit
from conftest import answer, failure, stage_of

runner = CliRunner()
SONNET = "anthropic/claude-sonnet-5.5"


def _init(workspace):
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0, result.output


def _run(workspace, *args, input=None):
    return runner.invoke(app, [*args, "--config", str(workspace.config)], input=input)


def _topic(workspace, name="unity"):
    return workspace.store / "topics" / name


def _patch(**parts):
    return answer("```json\n" + json.dumps(parts) + "\n```", cost=0.003)


def test_full_run_saves_memory_and_reports_the_change(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "Unity")

    assert result.exit_code == 0, result.output
    topic = _topic(workspace)
    memory = json.loads((topic / "memory.json").read_text(encoding="utf-8"))
    assert [c["text"] for c in memory["claims"]] == ["A claim."]
    assert memory["claims"][0]["added_run"].endswith("is-dots-ready")
    assert "**C1** A claim." in (topic / "summary.md").read_text(encoding="utf-8")
    assert "**D1**" in (topic / "disputes.md").read_text(encoding="utf-8")

    (run,) = sorted((topic / "runs").glob("*"))
    final = (run / "final.md").read_text(encoding="utf-8")
    assert final.rstrip().endswith(
        "## What changed in memory\n\n- Added C1: A claim. [agreed but unchecked]\n"
        "- Opened dispute D1: Whether the claim holds everywhere."
    )
    patch = json.loads((run / "memory_patch.json").read_text(encoding="utf-8"))
    assert patch["approved"] is None and patch["applied"]
    assert "Memory: nothing on this topic yet." in result.output
    assert "Topic memory updated: see `conclave show unity`." in result.output


def test_second_run_recalls_the_first(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")
    _run(workspace, "note", "unity", "We target mobile.")
    openrouter.chat_requests.clear()

    result = _run(workspace, "ask", "What about netcode?", "--full", "-t", "unity")

    assert result.exit_code == 0, result.output
    assert "Memory: recalled 1 claim, 1 open dispute, your notes." in result.output
    research = next(b for b in openrouter.chat_requests if stage_of(b) == "research")
    prompt = research["messages"][1]["content"]
    assert "## Earlier research on this topic" in prompt
    assert prompt.index("We target mobile.") < prompt.index("- C1: A claim.")
    assert "- D1: Whether the claim holds everywhere." in prompt
    assert prompt.rstrip().endswith("Question: What about netcode?")

    synthesis = next(b for b in openrouter.chat_requests if stage_of(b) == "synthesis")
    assert "- C1: A claim." in synthesis["messages"][1]["content"]
    memory_call = next(b for b in openrouter.chat_requests if stage_of(b) == "memory")
    assert "- C1: A claim. [agreed but unchecked]" in memory_call["messages"][1]["content"]

    runs = sorted((_topic(workspace) / "runs").glob("*"))
    assert "We target mobile." in (runs[-1] / "recall.md").read_text(encoding="utf-8")
    # The same claim was proposed again, so nothing new was added.
    memory = json.loads((_topic(workspace) / "memory.json").read_text(encoding="utf-8"))
    assert len(memory["claims"]) == 1


def test_quick_run_reads_memory_but_never_writes_it(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")
    before = (_topic(workspace) / "memory.json").read_text(encoding="utf-8")
    openrouter.chat_requests.clear()

    result = _run(workspace, "ask", "Quick one?", "-t", "unity")

    assert result.exit_code == 0, result.output
    assert openrouter.asked_in("memory") == []
    assert "- C1: A claim." in openrouter.chat_requests[0]["messages"][1]["content"]
    assert (_topic(workspace) / "memory.json").read_text(encoding="utf-8") == before


def test_fresh_neither_reads_nor_writes_memory(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")
    before = (_topic(workspace) / "memory.json").read_text(encoding="utf-8")
    openrouter.chat_requests.clear()

    result = _run(workspace, "ask", "Again?", "--full", "-t", "unity", "--fresh")

    assert result.exit_code == 0, result.output
    assert openrouter.asked_in("memory") == []
    assert all(
        "Earlier research" not in b["messages"][1]["content"] for b in openrouter.chat_requests
    )
    assert "Memory: not used (--fresh)." in result.output
    assert (_topic(workspace) / "memory.json").read_text(encoding="utf-8") == before


def test_review_can_decline_changes(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _run(
        workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity", "--review", input="n\n"
    )

    assert result.exit_code == 0, result.output
    assert "Proposed changes to the topic's memory:" in result.output
    assert "Added C1: A claim." in result.output
    assert not (_topic(workspace) / "memory.json").exists()
    (run,) = sorted((_topic(workspace) / "runs").glob("*"))
    assert json.loads((run / "memory_patch.json").read_text(encoding="utf-8"))["approved"] is False
    assert "Proposed changes were declined" in (run / "final.md").read_text(encoding="utf-8")


def test_review_can_accept_changes(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _run(
        workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity", "--review", input="y\n"
    )

    assert result.exit_code == 0, result.output
    assert (_topic(workspace) / "memory.json").exists()


def test_unreadable_patch_leaves_memory_alone(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.reply(SONNET, answer("I think the memory is fine."), stage="memory")

    result = _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")

    assert result.exit_code == 0, result.output
    assert not (_topic(workspace) / "memory.json").exists()
    (run,) = sorted((_topic(workspace) / "runs").glob("*"))
    assert (run / "memory_reply.md").exists()
    assert "not in the expected form" in result.output


def test_rules_are_enforced_on_the_models_patch(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.reply(
        SONNET,
        _patch(add=[{"text": "Only one model said this.", "label": "single model"}]),
        stage="memory",
    )

    _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")

    (run,) = sorted((_topic(workspace) / "runs").glob("*"))
    record = json.loads((run / "memory_patch.json").read_text(encoding="utf-8"))
    assert record["applied"] == []
    assert record["skipped"] == ["Not added, labelled 'single model': Only one model said this."]
    assert "## What changed in memory\n\nNo changes." in (run / "final.md").read_text(
        encoding="utf-8"
    )


def test_memory_failure_keeps_the_page(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.reply(SONNET, failure(429, "busy"), stage="memory")

    result = _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")

    assert result.exit_code == 0, result.output
    (run,) = sorted((_topic(workspace) / "runs").glob("*"))
    assert "The memory was not changed: the update failed." in (run / "final.md").read_text(
        encoding="utf-8"
    )


def test_broken_memory_file_stops_the_run_before_sending(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _topic(workspace).mkdir(parents=True)
    (_topic(workspace) / "memory.json").write_text("{broken", encoding="utf-8")

    result = _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")

    assert result.exit_code == 1
    assert "could not be read" in result.output
    assert openrouter.chat_requests == []


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_each_run_is_committed_when_the_store_is_a_git_repository(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    store = workspace.store
    subprocess.run(["git", "init", "-q"], cwd=store, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=store, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=store, check=True)

    _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")
    _run(workspace, "note", "unity", "We target mobile.")

    log = subprocess.run(
        ["git", "log", "--format=%s"], cwd=store, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert log == ["conclave: note on unity", "conclave: Is DOTS ready?"]
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=store, capture_output=True, text=True, check=True
    ).stdout
    assert "topics/unity/memory.json" in tracked
    assert "topics/unity/summary.md" in tracked
    assert "final.md" in tracked


@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_commit_keeps_to_conclave_paths_and_leaves_other_staged_files(tmp_path):
    store = tmp_path / "store"
    store.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=store, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=store, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=store, check=True)
    (store / "private.txt").write_text("secret", encoding="utf-8")
    subprocess.run(["git", "add", "private.txt"], cwd=store, check=True)
    memory = store / "topics" / "sky" / "memory.json"
    memory.parent.mkdir(parents=True)
    memory.write_text("{}\n", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("nope", encoding="utf-8")

    problem = commit(store, [memory, outside, store / "model-prices.json"], "conclave: test")

    assert problem is not None and "outside the research store" in problem
    committed = subprocess.run(
        ["git", "show", "--name-only", "--format=", "HEAD"],
        cwd=store,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "topics/sky/memory.json" in committed
    assert "private.txt" not in committed
    assert "outside.txt" not in committed
    staged = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=store,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert staged.strip() == "private.txt"


def test_fresh_and_review_together_is_refused(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _run(workspace, "ask", "Q?", "--full", "--fresh", "--review")

    assert result.exit_code == 1
    assert "nothing to --review" in result.output


def test_cut_off_memory_reply_is_not_applied(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    reply = '```json\n{"add": [{"text": "A claim", "label": "agreed but unchecked"}], "change'
    openrouter.reply(SONNET, answer(reply, finish_reason="length"), stage="memory")

    result = _run(workspace, "ask", "Is DOTS ready?", "--full", "-t", "unity")

    assert result.exit_code == 0, result.output
    assert not (_topic(workspace) / "memory.json").exists()
    assert "memory update reply was cut off at the length limit" in result.output
    assert "CUT OFF" in result.output
