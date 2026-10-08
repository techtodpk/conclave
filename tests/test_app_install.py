import os
import socket
from pathlib import Path

import pytest

pytest.importorskip("uvicorn")

from conclave.web import launch, shortcut  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def no_real_powershell(monkeypatch):
    """No test may create real shortcuts on the computer running the tests."""

    def refuse(script):
        raise AssertionError("a test tried to run PowerShell for real")

    monkeypatch.setattr(shortcut, "_powershell", refuse)


@pytest.fixture
def command(tmp_path, monkeypatch):
    exe = tmp_path / "bin" / "conclave"
    exe.parent.mkdir()
    exe.write_text("", encoding="utf-8")
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: str(exe))
    return exe


def test_linux_shortcut_opens_the_app(tmp_path, command):
    home = tmp_path / "home"
    (home / "Desktop").mkdir(parents=True)

    made = shortcut.create(home, platform="linux")

    assert {p.parent.name for p in made} == {"applications", "Desktop"}
    entry = made[0].read_text(encoding="utf-8")
    assert f'Exec="{command}" app' in entry
    assert "Terminal=true" in entry


def test_macos_shortcut_is_a_runnable_command_file(tmp_path, command):
    (launcher,) = shortcut.create(tmp_path, platform="darwin")

    assert launcher.name == "Conclave.command"
    assert launcher.read_text(encoding="utf-8") == f'#!/bin/bash\nexec "{command}" app\n'
    if os.name != "nt":  # Windows has no execute permission bit
        assert launcher.stat().st_mode & 0o111


def test_windows_shortcut_goes_on_the_desktop_and_start_menu(tmp_path, command, monkeypatch):
    scripts = []

    def fake(script):
        scripts.append(script)
        folder = "Desktop" if "'Desktop'" in script else "Start Menu"
        return f"C:\\Users\\Zoë O'Neil\\{folder}\\Conclave.lnk"

    monkeypatch.setattr(shortcut, "_powershell", fake)
    monkeypatch.setattr(shortcut.Path, "home", lambda: tmp_path / "O'Neil")

    made = shortcut.create(platform="win32")

    assert [str(p) for p in made] == [
        "C:\\Users\\Zoë O'Neil\\Desktop\\Conclave.lnk",
        "C:\\Users\\Zoë O'Neil\\Start Menu\\Conclave.lnk",
    ]  # the paths PowerShell reported, non-ASCII letters intact
    assert len(scripts) == 2
    assert "GetFolderPath('Desktop')" in scripts[0] and "GetFolderPath('Programs')" in scripts[1]
    assert "$s.Arguments = 'app'" in scripts[0]
    assert "O''Neil" in scripts[0]  # a quote in a path is doubled for PowerShell
    assert "conclave.ico" in scripts[0]


def test_missing_program_is_explained(monkeypatch):
    monkeypatch.setattr(shortcut.shutil, "which", lambda name: None)
    monkeypatch.setattr(shortcut.sys, "argv", ["python"])

    with pytest.raises(FileNotFoundError, match="Install Conclave"):
        shortcut.conclave_command()


def test_launcher_picks_a_free_port_and_skips_a_busy_one():
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        port = busy.getsockname()[1]
        assert launch._free(port) is False
        assert launch._running_at(port) is False  # something else, not Conclave


def test_installers_install_the_app_and_open_it():
    for name in ("install.ps1", "install.sh"):
        text = (ROOT / name).read_text(encoding="utf-8")
        assert "astral.sh/uv/install" in text, name
        assert '"conclave-council[app,mcp] @ ' in text, name
        assert "archive/refs/heads/main.zip" in text, name  # no Git needed on the user's machine
        assert "shortcut" in text and " app" in text, name


def test_only_a_codespace_trusts_its_forwarded_address(monkeypatch):
    monkeypatch.delenv("CODESPACE_NAME", raising=False)
    assert launch.codespace_hosts(8765) == set()

    monkeypatch.setenv("CODESPACE_NAME", "fuzzy-space-abc")
    monkeypatch.setenv("GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN", "app.github.dev")
    assert launch.codespace_hosts(8765) == {"fuzzy-space-abc-8765.app.github.dev"}
