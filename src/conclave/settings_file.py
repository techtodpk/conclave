"""Change the config file and the key file from the app, safely.

Every change is a small edit to the existing text, so the user's comments and layout
survive. After each edit the whole file is parsed again; if it no longer loads, the
original is put back and the change is refused.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from conclave.config import (
    Config,
    ConfigError,
    Member,
    default_config_text,
    load_config,
    parse_config,
)
from conclave.keys import KEY_NAME, key_locations, read_env_file

DEFAULT_STORE_LINE = 'path = "~/conclave-research"'
PROFILE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,39}$")
_HEADER = re.compile(r"^\[([A-Za-z0-9_.\-]+)\]\s*(#.*)?$")


class SettingsError(Exception):
    """A change could not be made. The message says why; the file is unchanged."""


def toml_value(value: object) -> str:
    """A Python value written as TOML."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return f"{value:.2f}" if round(value, 2) == value else repr(value)
    if isinstance(value, str):
        return json.dumps(value)  # a TOML basic string for ordinary text
    raise TypeError(f"cannot write {type(value).__name__} to the config")


def create_config(config_path: Path, store: Path | None = None) -> bool:
    """Write the default config if there is none. Returns whether it was created."""
    if config_path.exists():
        return False
    text = default_config_text()
    if store is not None:
        # as_posix keeps Windows paths valid inside a TOML string.
        text = text.replace(
            DEFAULT_STORE_LINE, f"path = {toml_value(store.expanduser().as_posix())}"
        )
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8")
    return True


def _sections(lines: list[str]) -> list[tuple[str, int, int]]:
    """(name, header line, end line) for every [section], end exclusive."""
    found = [(m.group(1), i) for i, line in enumerate(lines) if (m := _HEADER.match(line))]
    out = []
    for n, (name, start) in enumerate(found):
        end = found[n + 1][1] if n + 1 < len(found) else len(lines)
        # Comment lines just above the next header belong to that header.
        while end - 1 > start and (lines[end - 1].startswith("#") or not lines[end - 1].strip()):
            end -= 1
        out.append((name, start, end))
    return out


def set_value(text: str, section: str, key: str, value: object) -> str:
    """Set `key` in `[section]`, keeping everything else as it was."""
    lines = text.splitlines()
    line = f"{key} = {toml_value(value)}"
    pattern = re.compile(rf"^\s*{re.escape(key)}\s*=")
    for name, start, end in _sections(lines):
        if name != section:
            continue
        for i in range(start + 1, end):
            if pattern.match(lines[i]):
                lines[i] = line
                return "\n".join(lines) + "\n"
        lines.insert(end, line)
        return "\n".join(lines) + "\n"
    return text.rstrip("\n") + f"\n\n[{section}]\n{line}\n"


def _write_checked(config_path: Path, text: str) -> Config:
    """Write the new text only if it parses, so a bad change never reaches the file."""
    try:
        settings = parse_config(text)
    except ConfigError as error:
        raise SettingsError(f"Not saved: {error}") from None
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8")
    return settings


def update(config_path: Path, changes: dict[tuple[str, str], object]) -> Config:
    """Set several values at once, as {(section, key): value}. All or nothing."""
    if not config_path.exists():
        create_config(config_path)
    text = config_path.read_text(encoding="utf-8")
    for (section, key), value in changes.items():
        text = set_value(text, section, key, value)
    return _write_checked(config_path, text)


def profile_block(name: str, members: list[Member], chairman: Member, checker: Member) -> str:
    def table(member: Member) -> str:
        return f"{{ model = {toml_value(member.model)}, route = {toml_value(member.route)} }}"

    lines = [f"[profiles.{name}]", "members = ["]
    lines += [f"    {table(member)}," for member in members]
    lines += ["]", f"chairman = {table(chairman)}", f"checker = {table(checker)}"]
    return "\n".join(lines) + "\n"


def _without_section(text: str, section: str) -> tuple[str, bool]:
    lines = text.splitlines()
    for name, start, end in _sections(lines):
        if name == section:
            kept = lines[:start] + lines[end:]
            return "\n".join(kept).rstrip("\n") + "\n", True
    return text, False


def put_profile(
    config_path: Path,
    name: str,
    members: list[Member],
    chairman: Member,
    checker: Member,
    replace: bool = False,
) -> Config:
    """Add a council profile, or replace one when `replace` is set."""
    if not PROFILE_NAME.match(name):
        raise SettingsError(
            "A council name uses lowercase letters, digits, '-' and '_' only, up to 40 characters."
        )
    if not config_path.exists():
        create_config(config_path)
    text = config_path.read_text(encoding="utf-8")
    text, existed = _without_section(text, f"profiles.{name}")
    if existed and not replace:
        raise SettingsError(f"A council named '{name}' already exists.")
    block = profile_block(name, members, chairman, checker)
    return _write_checked(config_path, text.rstrip("\n") + "\n\n" + block)


def remove_profile(config_path: Path, name: str) -> Config:
    settings = load_config(config_path)
    if name not in settings.profiles:
        raise SettingsError(f"No council named '{name}'.")
    if name == settings.default_profile:
        raise SettingsError("This is the default council. Choose another default first.")
    text, _ = _without_section(config_path.read_text(encoding="utf-8"), f"profiles.{name}")
    return _write_checked(config_path, text)


# --- the API key -------------------------------------------------------------------


def key_file(config_path: Path) -> Path:
    """Where the app keeps the key: a .env file beside the config, outside any code folder."""
    return config_path.parent / ".env"


def save_api_key(config_path: Path, key: str) -> Path:
    """Store the key in the .env file beside the config, keeping any other lines there."""
    key = key.strip()
    if not key or any(c.isspace() for c in key) or len(key) > 300:
        raise SettingsError("That does not look like an API key. Copy it again from OpenRouter.")
    path = key_file(config_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    if path.is_file():
        lines = [
            line
            for line in path.read_text(encoding="utf-8-sig", errors="replace").splitlines()
            if not re.match(rf"^\s*(export\s+)?{KEY_NAME}\s*=", line)
        ]
    lines.append(f"{KEY_NAME}={key}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.name != "nt":
        path.chmod(0o600)
    return path


def key_hint(config_path: Path) -> dict[str, str] | None:
    """Where the key comes from and its last four characters. Never the key itself."""
    from_environment = os.environ.get(KEY_NAME, "").strip()
    if from_environment:
        return {"source": f"the {KEY_NAME} environment variable", "ends": from_environment[-4:]}
    for location in key_locations(config_path):
        value = read_env_file(location).get(KEY_NAME, "").strip()
        if value:
            return {"source": str(location), "ends": value[-4:]}
    return None
