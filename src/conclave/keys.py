"""Find the OpenRouter API key without ever printing or storing it."""

from __future__ import annotations

import os
from pathlib import Path

KEY_NAME = "OPENROUTER_API_KEY"


class MissingKeyError(Exception):
    """No API key could be found."""


def _read_text(path: Path) -> str:
    """Read a text file whatever encoding a Windows editor saved it in."""
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    # utf-8-sig drops the byte-order mark some editors put at the start of the file.
    return raw.decode("utf-8-sig", errors="replace")


def read_env_file(path: Path) -> dict[str, str]:
    """Read simple KEY=value lines from a .env file. Missing file gives an empty dict."""
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in _read_text(path).splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.removeprefix("export ").strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[name] = value
    return values


def key_locations(config_path: Path, cwd: Path | None = None) -> list[Path]:
    """The .env files that are checked, in order."""
    return [(cwd or Path.cwd()) / ".env", config_path.parent / ".env"]


def _what_was_found(location: Path) -> str:
    """A short note on why a location gave no key. Never includes the file's contents."""
    if location.is_file():
        return f"exists, but has no {KEY_NAME}=... line with a value"
    with_txt = location.with_name(location.name + ".txt")
    if with_txt.is_file():
        return f"not found, but {with_txt.name} is there. Rename it to .env (Notepad added .txt)"
    return "not found"


def load_api_key(config_path: Path, cwd: Path | None = None) -> str:
    """Return the key from the environment, else the first .env file that has one."""
    from_environment = os.environ.get(KEY_NAME, "").strip()
    if from_environment:
        return from_environment

    locations = key_locations(config_path, cwd)
    for location in locations:
        value = read_env_file(location).get(KEY_NAME, "").strip()
        if value:
            return value

    looked = "\n".join(f"  - {location}: {_what_was_found(location)}" for location in locations)
    raise MissingKeyError(
        f"No OpenRouter API key found. Set the {KEY_NAME} environment variable, "
        f"or put a line `{KEY_NAME}=your-key` in one of these files:\n{looked}\n"
        "Get a key at https://openrouter.ai/keys"
    )
