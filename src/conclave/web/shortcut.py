"""Put a "Conclave" shortcut on the desktop that opens the app."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

STATIC = Path(__file__).parent / "static"


def conclave_command() -> Path:
    """The installed `conclave` program that the shortcut should start."""
    found = shutil.which("conclave")
    if found:
        return Path(found)
    script = Path(sys.argv[0])
    if script.name.lower().startswith("conclave") and script.exists():
        return script.resolve()
    raise FileNotFoundError(
        "Could not find the conclave program. Install Conclave with the installer first."
    )


def _powershell(script: str) -> str:
    """Run a PowerShell script and return what it printed, read as UTF-8."""
    prefix = "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
    done = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", prefix + script],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if done.returncode != 0:
        raise OSError(done.stderr.strip() or f"PowerShell exited with {done.returncode}")
    return done.stdout.strip()


def _quoted(path: Path) -> str:
    """A PowerShell single-quoted string; a quote inside it is written twice."""
    return "'" + str(path).replace("'", "''") + "'"


def _windows(command: Path) -> list[Path]:
    """Shortcuts on the desktop and in the Start menu, made inside PowerShell.

    The folders are looked up and used in the same script, so a user name in any
    language never has to pass through the console's code page.
    """
    icon = STATIC / "conclave.ico"
    made = []
    for folder in ("Desktop", "Programs"):
        link = _powershell(
            f"$link = Join-Path ([Environment]::GetFolderPath('{folder}')) 'Conclave.lnk'; "
            "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($link); "
            f"$s.TargetPath = {_quoted(command)}; $s.Arguments = 'app'; "
            f"$s.WorkingDirectory = {_quoted(Path.home())}; $s.IconLocation = {_quoted(icon)}; "
            "$s.Description = 'Open Conclave in your browser'; $s.Save(); Write-Output $link"
        )
        made.append(Path(link))
    return made


def _macos(command: Path, home: Path) -> list[Path]:
    desktop = home / "Desktop"
    desktop.mkdir(exist_ok=True)
    launcher = desktop / "Conclave.command"
    launcher.write_text(f'#!/bin/bash\nexec "{command}" app\n', encoding="utf-8")
    launcher.chmod(0o755)
    return [launcher]


def _linux(command: Path, home: Path) -> list[Path]:
    entry = (
        "[Desktop Entry]\nType=Application\nName=Conclave\n"
        "Comment=Ask a council of AI models and keep what they conclude\n"
        f'Exec="{command}" app\nIcon={STATIC / "icon.svg"}\nTerminal=true\nCategories=Office;\n'
    )
    made = []
    applications = home / ".local" / "share" / "applications"
    applications.mkdir(parents=True, exist_ok=True)
    for folder in (applications, home / "Desktop"):
        if not folder.is_dir():
            continue
        target = folder / "conclave.desktop"
        target.write_text(entry, encoding="utf-8")
        target.chmod(0o755)
        made.append(target)
    return made


def create(home: Path | None = None, platform: str | None = None) -> list[Path]:
    """Create the shortcut for this computer. Returns the files made."""
    platform = platform or sys.platform
    command = conclave_command()
    if platform.startswith("win"):
        return _windows(command)
    if platform == "darwin":
        return _macos(command, home or Path.home())
    return _linux(command, home or Path.home())
