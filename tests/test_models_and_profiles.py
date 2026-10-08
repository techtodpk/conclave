from typer.testing import CliRunner

from conclave.cli import app
from conclave.config import load_config

runner = CliRunner()


def _init(workspace):
    result = runner.invoke(
        app, ["init", "--config", str(workspace.config), "--store", str(workspace.store)]
    )
    assert result.exit_code == 0, result.output


def test_models_lists_ids_with_prices_per_million(openrouter):
    result = runner.invoke(app, ["models"])

    assert result.exit_code == 0, result.output
    assert "per million tokens" in result.output
    lines = [line.split() for line in result.output.splitlines()]
    assert ["anthropic/claude-sonnet-5.5", "2.000", "10.000", "1,000,000"] in lines
    assert ["deepseek/deepseek-v4.1-flash", "0.055", "1.320", "1,000,000"] in lines


def test_models_search_sort_and_limit(openrouter):
    searched = runner.invoke(app, ["models", "--search", "claude", "--sort", "price"])
    limited = runner.invoke(app, ["models", "--limit", "2"])
    nothing = runner.invoke(app, ["models", "--vendor", "nobody"])
    bad_sort = runner.invoke(app, ["models", "--sort", "size"])

    rows = [line.split()[0] for line in searched.output.splitlines() if "/" in line]
    assert rows == ["anthropic/claude-sonnet-5.5", "anthropic/claude-opus-5.5"]
    assert "Showing 2 of 5" in limited.output
    assert "No models match" in nothing.output
    assert bad_sort.exit_code == 1


def test_models_reports_when_the_list_is_unavailable(openrouter):
    openrouter.models_status = 500

    result = runner.invoke(app, ["models"])

    assert result.exit_code == 1
    assert "Could not list models" in result.output


def _add(workspace, name, *args):
    return runner.invoke(app, ["profile", "add", name, *args, "--config", str(workspace.config)])


def test_profile_add_writes_a_valid_profile_and_keeps_the_rest(workspace, openrouter):
    _init(workspace)
    before = workspace.config.read_text(encoding="utf-8")

    result = _add(
        workspace,
        "mine",
        "--members",
        "google/gemini-3.8-flash,deepseek/deepseek-v4.1-flash",
        "--chairman",
        "anthropic/claude-opus-5.5",
    )

    assert result.exit_code == 0, result.output
    after = workspace.config.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n"))
    assert "# Conclave configuration." in after
    profile = load_config(workspace.config).profile("mine")
    assert [m.model for m in profile.members] == [
        "google/gemini-3.8-flash",
        "deepseek/deepseek-v4.1-flash",
    ]
    assert profile.chairman.model == "anthropic/claude-opus-5.5"
    assert profile.checker.model == "anthropic/claude-opus-5.5"
    assert "--profile mine" in result.output
    assert "Warning" not in result.output


def test_profile_add_warns_about_a_shared_vendor(workspace, openrouter):
    _init(workspace)

    result = _add(
        workspace,
        "claudes",
        "--members",
        "anthropic/claude-sonnet-5.5,anthropic/claude-opus-5.5",
        "--chairman",
        "openai/gpt-6.1-sol",
        "--checker",
        "google/gemini-3.8-flash",
    )

    assert result.exit_code == 0, result.output
    assert "more than one member comes from anthropic" in result.output
    assert load_config(workspace.config).profile("claudes").checker.model == (
        "google/gemini-3.8-flash"
    )


def test_profile_add_rejects_bad_input_and_leaves_the_config_alone(workspace, openrouter):
    _init(workspace)
    before = workspace.config.read_text(encoding="utf-8")
    good = ["--members", "google/gemini-3.8-flash,openai/gpt-6.1-sol"]
    chair = ["--chairman", "anthropic/claude-opus-5.5"]

    unknown = _add(workspace, "a", "--members", "google/gemini-9,openai/gpt-6.1-sol", *chair)
    duplicate = _add(workspace, "balanced", *good, *chair)
    bad_name = _add(workspace, "My Profile", *good, *chair)
    one_member = _add(workspace, "b", "--members", "google/gemini-3.8-flash", *chair)
    two_chairs = _add(workspace, "c", *good, "--chairman", "a/b,c/d")

    assert unknown.exit_code == 1
    assert "'google/gemini-9' is not in OpenRouter's model list" in unknown.output
    assert "google/gemini-3.8-flash" in unknown.output
    assert duplicate.exit_code == 1 and "already exists" in duplicate.output
    assert bad_name.exit_code == 1 and "lowercase" in bad_name.output
    assert one_member.exit_code == 1 and "at least 2" in one_member.output
    assert two_chairs.exit_code == 1 and "exactly one" in two_chairs.output
    assert workspace.config.read_text(encoding="utf-8") == before


def test_profile_add_can_skip_the_live_check(workspace, openrouter):
    _init(workspace)
    openrouter.models_status = 503
    args = ["--members", "x/one,y/two", "--chairman", "z/three"]

    refused = _add(workspace, "offline", *args)
    added = _add(workspace, "offline", *args, "--no-check")

    assert refused.exit_code == 1 and "--no-check" in refused.output
    assert added.exit_code == 0, added.output
    assert load_config(workspace.config).profile("offline").chairman.model == "z/three"


def test_profile_add_needs_a_config_file(workspace, openrouter):
    result = _add(workspace, "mine", "--members", "a/b,c/d", "--chairman", "e/f")

    assert result.exit_code == 1
    assert "conclave init" in result.output
