import json

from typer.testing import CliRunner

from conclave.cli import app
from conftest import KEY, answer, failure

runner = CliRunner()

BALANCED = ["anthropic/claude-sonnet-5.5", "openai/gpt-6.1-sol", "google/gemini-3.8-flash"]


def _init(workspace):
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0, result.output


def _ask(workspace, *args):
    return runner.invoke(app, ["ask", *args, "--config", str(workspace.config)])


def _edit_config(workspace, old, new):
    text = workspace.config.read_text(encoding="utf-8")
    assert old in text
    workspace.config.write_text(text.replace(old, new), encoding="utf-8")


def test_full_run_saves_an_answer_from_every_member(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _ask(workspace, "Is Unity DOTS ready for production?", "--full", "--topic", "Unity")

    assert result.exit_code == 0, result.output
    assert sorted(openrouter.asked) == sorted(BALANCED)
    (run,) = workspace.runs("unity")
    assert run.name.endswith("is-unity-dots-ready-for-production")
    answers = sorted(path.name for path in (run / "answers").iterdir())
    assert answers == [
        "anthropic--claude-sonnet-5.5.md",
        "google--gemini-3.8-flash.md",
        "openai--gpt-6.1-sol.md",
    ]
    gemini = (run / "answers" / "google--gemini-3.8-flash.md").read_text(encoding="utf-8")
    assert "model: google/gemini-3.8-flash" in gemini
    assert "Answer from google/gemini-3.8-flash." in gemini
    assert "Is Unity DOTS ready for production?" in (run / "question.md").read_text(
        encoding="utf-8"
    )

    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "full"
    assert meta["profile"] == "balanced"
    assert meta["topic"] == "unity"
    assert meta["stages"] == ["research"]
    assert meta["totals"]["answers"] == 3
    assert meta["totals"]["failures"] == 0
    assert meta["totals"]["cost_usd"] == 0.012
    assert meta["totals"]["prompt_tokens"] == 900
    assert meta["budget"]["cap_usd"] == 0.75
    assert 0 < meta["budget"]["worst_case_estimate_usd"] < 0.75
    assert {seat["cost_source"] for seat in meta["seats"]} == {"reported"}

    assert "Asked 3 members (profile 'balanced', topic 'unity')" in result.output
    assert "$0.0120 of the $0.75 cap for full runs" in result.output
    assert str(run) in result.output.replace("\n", "")


def test_the_question_and_date_reach_the_model(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    _ask(workspace, "Why is the sky blue?")

    body = openrouter.chat_requests[0]
    assert body["max_tokens"] == 1500
    assert body["messages"][0]["role"] == "system"
    assert "## Key claims" in body["messages"][0]["content"]
    assert "Question: Why is the sky blue?" in body["messages"][1]["content"]
    assert "Today's date: " in body["messages"][1]["content"]
    assert openrouter.auth_headers == [f"Bearer {KEY}"]


def test_quick_run_asks_only_the_chairman_and_prints_the_answer(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.reply("anthropic/claude-sonnet-5.5", answer("## Answer\n\nRayleigh scattering."))

    result = _ask(workspace, "Why is the sky blue?")

    assert result.exit_code == 0, result.output
    assert openrouter.asked == ["anthropic/claude-sonnet-5.5"]
    assert "Rayleigh scattering." in result.output
    assert "Asked the chairman" in result.output
    (run,) = workspace.runs()
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    assert meta["mode"] == "quick"
    assert meta["seats"][0]["role"] == "chairman"
    assert meta["budget"]["cap_usd"] == 0.05


def test_one_failure_does_not_lose_the_other_answers(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.reply("openai/gpt-6.1-sol", failure(402, "no credit"))

    result = _ask(workspace, "A question", "--full")

    assert result.exit_code == 0, result.output
    (run,) = workspace.runs()
    assert len(list((run / "answers").iterdir())) == 2
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    assert meta["totals"]["answers"] == 2
    assert meta["totals"]["failures"] == 1
    failed = next(seat for seat in meta["seats"] if seat["status"] == "error")
    assert failed["model"] == "openai/gpt-6.1-sol"
    assert "out of credit" in failed["error"]
    assert "FAILED" in result.output


def test_all_failures_exit_with_an_error(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    for model in BALANCED:
        openrouter.reply(model, failure(401, "bad key"))

    result = _ask(workspace, "A question", "--full")

    assert result.exit_code == 1
    assert result.output.count("FAILED") == 3
    assert "nothing was saved" in result.output
    assert workspace.runs() == []
    assert KEY not in result.output


def test_members_option_overrides_the_profile(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _ask(
        workspace, "A question", "--members", "deepseek/deepseek-v4.1-flash, openai/gpt-6.1-sol"
    )

    assert result.exit_code == 0, result.output
    assert sorted(openrouter.asked) == ["deepseek/deepseek-v4.1-flash", "openai/gpt-6.1-sol"]
    assert "Asked 2 members" in result.output


def test_named_profile_is_used(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _ask(workspace, "A question", "--full", "--profile", "full")

    assert result.exit_code == 0, result.output
    assert len(openrouter.asked) == 4
    assert "deepseek/deepseek-v4.1-flash" in openrouter.asked


def test_unknown_model_stops_before_anything_is_sent(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    result = _ask(
        workspace, "A question", "--members", "anthropic/claude-sonnet-9,openai/gpt-6.1-sol"
    )

    assert result.exit_code == 1
    assert "'anthropic/claude-sonnet-9' is not in OpenRouter's model list" in result.output
    assert "anthropic/claude-sonnet-5.5" in result.output
    assert openrouter.chat_requests == []
    assert workspace.runs() == []


def test_run_above_the_cap_is_refused_before_anything_is_sent(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _edit_config(workspace, "full_run_usd = 0.75", "full_run_usd = 0.001")

    result = _ask(workspace, "A question", "--full")

    assert result.exit_code == 1
    assert "could cost up to" in result.output
    assert "Nothing was sent" in result.output
    assert openrouter.chat_requests == []
    assert workspace.runs() == []


def test_monthly_cap_pauses_full_runs_but_not_quick_ones(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _edit_config(workspace, "monthly_usd = 15.00", "monthly_usd = 0.01")
    assert _ask(workspace, "First question", "--full").exit_code == 0  # costs 0.012

    blocked = _ask(workspace, "Second question", "--full")
    allowed = _ask(workspace, "Third question", "--quick")

    assert blocked.exit_code == 1
    assert "full runs are paused" in blocked.output
    assert allowed.exit_code == 0, allowed.output
    assert len(workspace.runs()) == 2


def test_missing_key_says_where_to_put_it(workspace, openrouter):
    _init(workspace)

    result = _ask(workspace, "A question")

    assert result.exit_code == 1
    assert "No OpenRouter API key found" in result.output
    assert str(workspace.cwd / ".env") in result.output.replace("\n", "")
    assert openrouter.chat_requests == []
    assert openrouter.model_list_requests == 0


def test_key_is_read_from_an_env_file(workspace, openrouter):
    _init(workspace)
    (workspace.cwd / ".env").write_text(f"OPENROUTER_API_KEY={KEY}\n", encoding="utf-8")

    result = _ask(workspace, "A question")

    assert result.exit_code == 0, result.output
    assert openrouter.auth_headers == [f"Bearer {KEY}"]


def test_run_continues_when_prices_are_unavailable(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.models_status = 503

    result = _ask(workspace, "A question", "--full")

    assert result.exit_code == 0, result.output
    assert "Prices unavailable" in result.output
    (run,) = workspace.runs()
    meta = json.loads((run / "meta.json").read_text(encoding="utf-8"))
    assert meta["budget"]["worst_case_estimate_usd"] is None
    assert meta["totals"]["cost_usd"] == 0.012


def test_cost_is_estimated_from_prices_when_not_reported(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    openrouter.reply("anthropic/claude-sonnet-5.5", answer(cost=None))

    result = _ask(workspace, "A question")

    assert result.exit_code == 0, result.output
    assert "(estimated)" in result.output
    (run,) = workspace.runs()
    seat = json.loads((run / "meta.json").read_text(encoding="utf-8"))["seats"][0]
    assert seat["cost_source"] == "estimated"
    assert seat["cost_usd"] == 300 * 0.000002 + 200 * 0.00001


def test_conflicting_or_empty_input_is_refused(workspace, openrouter):
    _init(workspace)
    workspace.set_key()

    both = _ask(workspace, "A question", "--full", "--quick")
    empty = _ask(workspace, "   ")
    one = _ask(workspace, "A question", "--members", "openai/gpt-6.1-sol")
    quick_members = _ask(workspace, "A question", "--quick", "--members", "a/b,c/d")
    missing_profile = _ask(workspace, "A question", "--profile", "nope")

    assert both.exit_code == 1 and "not both" in both.output
    assert empty.exit_code == 1 and "empty" in empty.output
    assert one.exit_code == 1 and "at least 2" in one.output
    assert quick_members.exit_code == 1 and "--quick" in quick_members.output
    assert missing_profile.exit_code == 1 and "Known profiles" in missing_profile.output
    assert openrouter.chat_requests == []


def test_command_line_route_is_refused_for_now(workspace, openrouter):
    _init(workspace)
    workspace.set_key()
    _edit_config(
        workspace,
        'chairman = { model = "anthropic/claude-sonnet-5.5", route = "api" }\n'
        'checker = { model = "anthropic/claude-sonnet-5.5", route = "api" }',
        'chairman = { model = "anthropic/claude-sonnet-5.5", route = "cli" }\n'
        'checker = { model = "anthropic/claude-sonnet-5.5", route = "api" }',
    )

    result = _ask(workspace, "A question")

    assert result.exit_code == 1
    assert "milestone 7" in result.output
    assert openrouter.chat_requests == []


def test_ask_works_before_init_using_the_defaults(workspace, openrouter, monkeypatch, tmp_path):
    workspace.set_key()
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "home"))

    result = _ask(workspace, "A question")

    assert result.exit_code == 0, result.output
    assert (tmp_path / "home" / "conclave-research" / "topics" / "general" / "runs").is_dir()
