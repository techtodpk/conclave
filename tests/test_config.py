from pathlib import Path

import pytest

from conclave.config import (
    ConfigError,
    default_config_path,
    default_config_text,
    load_config,
    parse_config,
)

MINIMAL = """
[store]
path = "~/somewhere"

[run]
default_profile = "duo"
default_mode = "quick"
claims_checked = 5

[budget]
full_run_usd = 0.75
quick_run_usd = 0.05
monthly_usd = 15

[profiles.duo]
members = ["alpha/one", "beta/two"]
chairman = "alpha/one"
checker = { model = "beta/two", route = "cli" }
"""


def test_packaged_defaults_are_valid():
    config = parse_config(default_config_text())

    assert set(config.profiles) == {"lean", "balanced", "full"}
    assert config.default_profile == "balanced"
    assert config.default_mode == "quick"
    assert config.budget.full_run_usd == 1.00
    assert config.budget.quick_run_usd == 0.10
    assert config.budget.monthly_usd == 15.0


def test_packaged_profiles_spread_members_across_vendors():
    config = parse_config(default_config_text())

    for profile in config.profiles.values():
        assert profile.shared_vendors() == [], profile.name


def test_store_path_expands_home():
    config = parse_config(MINIMAL)

    assert config.store_path == Path.home() / "somewhere"


def test_member_can_be_a_plain_id_or_a_table():
    profile = parse_config(MINIMAL).profile()

    assert [member.model for member in profile.members] == ["alpha/one", "beta/two"]
    assert profile.members[0].route == "api"
    assert profile.checker.route == "cli"
    assert profile.chairman.vendor == "alpha"


def test_shared_vendors_are_reported():
    text = MINIMAL.replace('"beta/two"]', '"alpha/two"]')

    assert parse_config(text).profile().shared_vendors() == ["alpha"]


def test_unknown_profile_names_the_known_ones():
    config = parse_config(MINIMAL)

    with pytest.raises(ConfigError, match="Known profiles: duo"):
        config.profile("missing")


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('default_profile = "duo"', 'default_profile = "nope"', "not a profile"),
        ('default_mode = "quick"', 'default_mode = "fast"', "default_mode"),
        ("claims_checked = 5", "claims_checked = -1", "claims_checked"),
        ("full_run_usd = 0.75", "full_run_usd = 0", "full_run_usd"),
        ('route = "cli"', 'route = "browser"', "route must be one of"),
        ('"alpha/one", "beta/two"', '"alpha/one"', "at least 2"),
        ('chairman = "alpha/one"', 'chairman = "no-vendor"', "vendor/model-name"),
        ('chairman = "alpha/one"\n', "", "chairman is required"),
        ("[budget]", "[budgets]", r"missing section \[budget\]"),
    ],
)
def test_invalid_values_are_rejected(old, new, message):
    assert old in MINIMAL

    with pytest.raises(ConfigError, match=message):
        parse_config(MINIMAL.replace(old, new))


def test_broken_toml_is_a_config_error():
    with pytest.raises(ConfigError, match="not valid TOML"):
        parse_config("[store\npath = ")


def test_load_uses_defaults_when_no_file(tmp_path):
    config = load_config(tmp_path / "absent.toml")

    assert config.default_profile == "balanced"


def test_load_reads_the_file_and_names_it_in_errors(tmp_path):
    good = tmp_path / "good.toml"
    good.write_text(MINIMAL, encoding="utf-8")
    assert load_config(good).default_profile == "duo"

    bad = tmp_path / "bad.toml"
    bad.write_text(MINIMAL.replace("monthly_usd = 15", "monthly_usd = -3"), encoding="utf-8")
    with pytest.raises(ConfigError, match="bad.toml"):
        load_config(bad)


def test_config_path_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("CONCLAVE_CONFIG", str(tmp_path / "custom.toml"))
    assert default_config_path() == tmp_path / "custom.toml"

    monkeypatch.delenv("CONCLAVE_CONFIG")
    assert default_config_path() == Path.home() / ".conclave" / "config.toml"


def test_max_answer_tokens_defaults_and_is_validated():
    assert parse_config(MINIMAL).max_answer_tokens == 1500

    custom = MINIMAL.replace("claims_checked = 5", "claims_checked = 5\nmax_answer_tokens = 800")
    assert parse_config(custom).max_answer_tokens == 800

    too_small = MINIMAL.replace("claims_checked = 5", "claims_checked = 5\nmax_answer_tokens = 5")
    with pytest.raises(ConfigError, match="max_answer_tokens"):
        parse_config(too_small)


def test_budget_cap_depends_on_the_mode():
    budget = parse_config(MINIMAL).budget

    assert budget.cap_for("full") == 0.75
    assert budget.cap_for("quick") == 0.05


def test_reasoning_defaults_to_low_and_is_validated():
    assert parse_config(MINIMAL).reasoning == "low"
    assert parse_config(default_config_text()).reasoning == "low"
    text = MINIMAL.replace("claims_checked = 5", 'claims_checked = 5\nreasoning = "none"')
    assert parse_config(text).reasoning == "none"

    with pytest.raises(ConfigError, match="run.reasoning must be one of"):
        parse_config(MINIMAL.replace("claims_checked = 5", 'claims_checked = 5\nreasoning = "max"'))


def test_search_is_on_by_default_and_can_be_set():
    assert (parse_config(MINIMAL).web_search, parse_config(MINIMAL).max_searches) == (True, 3)
    config = parse_config(MINIMAL + "\n[search]\nenabled = false\nmax_searches = 5\n")
    assert (config.web_search, config.max_searches) == (False, 5)
    packaged = parse_config(default_config_text())
    assert (packaged.web_search, packaged.max_searches) == (True, 3)

    with pytest.raises(ConfigError, match="search.max_searches"):
        parse_config(MINIMAL + "\n[search]\nmax_searches = 0\n")
    with pytest.raises(ConfigError, match="search.enabled"):
        parse_config(MINIMAL + '\n[search]\nenabled = "yes"\n')
