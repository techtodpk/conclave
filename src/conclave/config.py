"""Load and validate Conclave's configuration.

The configuration is one TOML file. When no file exists yet, the defaults that
ship with the package are used, so every command works before `conclave init`.
"""

from __future__ import annotations

import os
import tomllib
from collections import Counter
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

CONFIG_ENV = "CONCLAVE_CONFIG"
ROUTES = ("api", "cli")
MODES = ("quick", "full")
MIN_MEMBERS = 2
DEFAULT_MAX_ANSWER_TOKENS = 1500
# How hard reasoning models think before answering (OpenRouter's reasoning effort).
REASONING_LEVELS = ("none", "minimal", "low", "medium", "high")
DEFAULT_REASONING = "low"
# Web searches each member may run per answer in a full run (decision 0011).
DEFAULT_MAX_SEARCHES = 3
MAX_SEARCHES_LIMIT = 10
MIN_ANSWER_TOKENS = 100


class ConfigError(Exception):
    """The configuration file is missing something or holds an invalid value."""


@dataclass(frozen=True)
class Member:
    """One model and the route used to reach it."""

    model: str
    route: str = "api"

    @property
    def vendor(self) -> str:
        """The lab that makes the model: the part of the id before the slash."""
        return self.model.split("/", 1)[0]


@dataclass(frozen=True)
class Profile:
    """A named council: who answers, who chairs, who checks."""

    name: str
    members: tuple[Member, ...]
    chairman: Member
    checker: Member

    def shared_vendors(self) -> list[str]:
        """Vendors that supply more than one member, in alphabetical order."""
        counts = Counter(member.vendor for member in self.members)
        return sorted(vendor for vendor, count in counts.items() if count > 1)


@dataclass(frozen=True)
class Budget:
    """Spending caps in US dollars."""

    full_run_usd: float
    quick_run_usd: float
    monthly_usd: float

    def cap_for(self, mode: str) -> float:
        """The per-run cap that applies to a run in this mode."""
        return self.full_run_usd if mode == "full" else self.quick_run_usd


@dataclass(frozen=True)
class Config:
    store_path: Path
    default_profile: str
    default_mode: str
    claims_checked: int
    budget: Budget
    profiles: dict[str, Profile]
    max_answer_tokens: int = DEFAULT_MAX_ANSWER_TOKENS
    reasoning: str = DEFAULT_REASONING
    web_search: bool = True
    max_searches: int = DEFAULT_MAX_SEARCHES

    def profile(self, name: str | None = None) -> Profile:
        """Return the named profile, or the default one when no name is given."""
        wanted = name or self.default_profile
        try:
            return self.profiles[wanted]
        except KeyError:
            known = ", ".join(sorted(self.profiles))
            raise ConfigError(f"No profile named '{wanted}'. Known profiles: {known}.") from None


def default_config_path() -> Path:
    """Where the config file lives: $CONCLAVE_CONFIG, else ~/.conclave/config.toml."""
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".conclave" / "config.toml"


def default_config_text() -> str:
    """The config template that ships with the package."""
    return resources.files("conclave").joinpath("default_config.toml").read_text(encoding="utf-8")


def load_config(path: Path | None = None) -> Config:
    """Load the config file at `path`, or the packaged defaults if it does not exist."""
    config_path = path or default_config_path()
    if config_path.is_file():
        text = config_path.read_text(encoding="utf-8")
        source = str(config_path)
    else:
        text = default_config_text()
        source = "built-in defaults"
    try:
        return parse_config(text)
    except ConfigError as error:
        raise ConfigError(f"{source}: {error}") from None


def parse_config(text: str) -> Config:
    """Turn TOML text into a validated Config."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"not valid TOML ({error})") from None

    store = _table(data, "store")
    run = _table(data, "run")
    budget = _table(data, "budget")
    raw_profiles = _table(data, "profiles")

    if not raw_profiles:
        raise ConfigError("at least one profile is required under [profiles]")
    profiles = {name: _profile(name, raw) for name, raw in raw_profiles.items()}

    default_profile = _text(run, "default_profile", "run")
    if default_profile not in profiles:
        known = ", ".join(sorted(profiles))
        raise ConfigError(
            f"run.default_profile is '{default_profile}', which is not a profile. Known: {known}."
        )

    default_mode = _text(run, "default_mode", "run")
    if default_mode not in MODES:
        raise ConfigError(f"run.default_mode must be one of {', '.join(MODES)}")

    claims_checked = run.get("claims_checked")
    if (
        not isinstance(claims_checked, int)
        or isinstance(claims_checked, bool)
        or claims_checked < 0
    ):
        raise ConfigError("run.claims_checked must be a whole number, 0 or more")

    max_answer_tokens = run.get("max_answer_tokens", DEFAULT_MAX_ANSWER_TOKENS)
    if (
        not isinstance(max_answer_tokens, int)
        or isinstance(max_answer_tokens, bool)
        or max_answer_tokens < MIN_ANSWER_TOKENS
    ):
        raise ConfigError(
            f"run.max_answer_tokens must be a whole number, {MIN_ANSWER_TOKENS} or more"
        )

    reasoning = run.get("reasoning", DEFAULT_REASONING)
    if reasoning not in REASONING_LEVELS:
        raise ConfigError(f"run.reasoning must be one of {', '.join(REASONING_LEVELS)}")

    search = data.get("search", {})
    if not isinstance(search, dict):
        raise ConfigError("[search] must be a section")
    web_search = search.get("enabled", True)
    if not isinstance(web_search, bool):
        raise ConfigError("search.enabled must be true or false")
    max_searches = search.get("max_searches", DEFAULT_MAX_SEARCHES)
    if (
        not isinstance(max_searches, int)
        or isinstance(max_searches, bool)
        or not 1 <= max_searches <= MAX_SEARCHES_LIMIT
    ):
        raise ConfigError(
            f"search.max_searches must be a whole number from 1 to {MAX_SEARCHES_LIMIT}"
        )

    return Config(
        store_path=Path(_text(store, "path", "store")).expanduser(),
        default_profile=default_profile,
        default_mode=default_mode,
        claims_checked=claims_checked,
        budget=Budget(
            full_run_usd=_amount(budget, "full_run_usd"),
            quick_run_usd=_amount(budget, "quick_run_usd"),
            monthly_usd=_amount(budget, "monthly_usd"),
        ),
        profiles=profiles,
        max_answer_tokens=max_answer_tokens,
        reasoning=reasoning,
        web_search=web_search,
        max_searches=max_searches,
    )


def _table(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = data.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"missing section [{key}]")
    return value


def _text(table: dict[str, Any], key: str, section: str) -> str:
    value = table.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{section}.{key} must be a non-empty string")
    return value.strip()


def _amount(table: dict[str, Any], key: str) -> float:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"budget.{key} must be a number greater than 0")
    return float(value)


def parse_member(raw: Any, where: str = "member") -> Member:
    """Accept either "vendor/model" or { model = "vendor/model", route = "api" }."""
    if isinstance(raw, str):
        model, route = raw, "api"
    elif isinstance(raw, dict):
        model, route = raw.get("model"), raw.get("route", "api")
    else:
        raise ConfigError(f"{where} must be a model id or a table with a 'model' key")

    if not isinstance(model, str) or "/" not in model.strip("/"):
        raise ConfigError(f"{where}: model must look like 'vendor/model-name'")
    if route not in ROUTES:
        raise ConfigError(f"{where}: route must be one of {', '.join(ROUTES)}")
    return Member(model=model.strip(), route=route)


def _profile(name: str, raw: Any) -> Profile:
    where = f"profiles.{name}"
    if not isinstance(raw, dict):
        raise ConfigError(f"{where} must be a table")

    raw_members = raw.get("members")
    if not isinstance(raw_members, list) or len(raw_members) < MIN_MEMBERS:
        raise ConfigError(f"{where}.members must list at least {MIN_MEMBERS} models")
    members = tuple(
        parse_member(item, f"{where}.members[{index}]") for index, item in enumerate(raw_members)
    )

    for role in ("chairman", "checker"):
        if role not in raw:
            raise ConfigError(f"{where}.{role} is required")

    return Profile(
        name=name,
        members=members,
        chairman=parse_member(raw["chairman"], f"{where}.chairman"),
        checker=parse_member(raw["checker"], f"{where}.checker"),
    )
