import os

import pytest

from conclave.config import Member, load_config
from conclave.keys import KEY_NAME, load_api_key
from conclave.settings_file import (
    SettingsError,
    create_config,
    key_hint,
    put_profile,
    remove_profile,
    save_api_key,
    set_value,
    update,
)

A, B, C = Member("anthropic/x"), Member("openai/y"), Member("google/z")


@pytest.fixture
def config(tmp_path):
    path = tmp_path / "home" / "config.toml"
    assert create_config(path, tmp_path / "store")
    return path


def test_create_config_is_safe_to_repeat_and_sets_the_store(tmp_path, config):
    assert not create_config(config)
    assert load_config(config).store_path == tmp_path / "store"


def test_values_change_in_place_and_comments_survive(config):
    before = config.read_text(encoding="utf-8")

    settings = update(
        config,
        {
            ("budget", "monthly_usd"): 20.0,
            ("search", "enabled"): False,
            ("search", "max_searches"): 2,
            ("run", "default_profile"): "lean",
        },
    )

    after = config.read_text(encoding="utf-8")
    assert settings.budget.monthly_usd == 20.0
    assert (settings.web_search, settings.max_searches) == (False, 2)
    assert settings.default_profile == "lean"
    assert "monthly_usd = 20.00" in after
    assert after.count("# Spending limits in US dollars") == before.count(
        "# Spending limits in US dollars"
    )
    assert len(after.splitlines()) == len(before.splitlines())


def test_a_missing_key_or_section_is_added():
    text = '[run]\ndefault_mode = "quick"\n\n# about budgets\n[budget]\nfull_run_usd = 1.0\n'

    added = set_value(text, "run", "reasoning", "low")
    assert added.index('reasoning = "low"') < added.index("# about budgets")
    assert set_value(text, "search", "enabled", True).endswith("[search]\nenabled = true\n")


def test_an_invalid_change_is_refused_and_the_file_is_unchanged(config):
    before = config.read_text(encoding="utf-8")

    with pytest.raises(SettingsError, match="monthly_usd"):
        update(config, {("budget", "monthly_usd"): 0.0})
    with pytest.raises(SettingsError, match="not a profile"):
        update(config, {("run", "default_profile"): "nope"})

    assert config.read_text(encoding="utf-8") == before


def test_profiles_are_added_replaced_and_removed(config):
    put_profile(config, "mine", [A, B], A, C)
    assert [m.model for m in load_config(config).profile("mine").members] == [A.model, B.model]

    with pytest.raises(SettingsError, match="already exists"):
        put_profile(config, "mine", [A, B], A, C)
    put_profile(config, "mine", [A, B, C], B, B, replace=True)
    profile = load_config(config).profile("mine")
    assert (len(profile.members), profile.chairman.model) == (3, B.model)
    assert config.read_text(encoding="utf-8").count("[profiles.mine]") == 1

    remove_profile(config, "mine")
    assert "mine" not in load_config(config).profiles
    assert {"lean", "balanced", "full"} <= set(load_config(config).profiles)


def test_profile_rules(config):
    with pytest.raises(SettingsError, match="lowercase"):
        put_profile(config, "My Council", [A, B], A, A)
    with pytest.raises(SettingsError, match="at least 2"):
        put_profile(config, "solo", [A], A, A)
    with pytest.raises(SettingsError, match="default council"):
        remove_profile(config, "balanced")
    assert "solo" not in load_config(config).profiles


def test_key_is_saved_beside_the_config_and_only_its_end_is_shown(config, monkeypatch, tmp_path):
    monkeypatch.delenv(KEY_NAME, raising=False)
    monkeypatch.chdir(tmp_path)
    env = config.parent / ".env"
    env.write_text("OTHER=1\nOPENROUTER_API_KEY=old\n", encoding="utf-8")

    save_api_key(config, "  sk-or-v1-abcdef1234  ")

    assert env.read_text(encoding="utf-8") == "OTHER=1\nOPENROUTER_API_KEY=sk-or-v1-abcdef1234\n"
    assert load_api_key(config) == "sk-or-v1-abcdef1234"
    hint = key_hint(config)
    assert hint == {"source": str(env), "ends": "1234"}
    if os.name != "nt":
        assert env.stat().st_mode & 0o777 == 0o600


def test_bad_keys_are_refused(config):
    for bad in ("", "two words", "x" * 301):
        with pytest.raises(SettingsError, match="does not look like an API key"):
            save_api_key(config, bad)


def test_no_key_gives_no_hint(config, monkeypatch, tmp_path):
    monkeypatch.delenv(KEY_NAME, raising=False)
    monkeypatch.chdir(tmp_path)
    assert key_hint(config) is None
