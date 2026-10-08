"""Commit memory changes when the research store is a Git repository."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def is_repository(store: Path) -> bool:
    return (store / ".git").exists()


def commit(store: Path, paths: list[Path], message: str) -> str | None:
    """Commit the given paths. Returns None on success, or why it did not commit.

    Does nothing when the store is not a Git repository. Never raises: a failed commit
    must not lose a run that is already saved.
    """
    if not is_repository(store):
        return None
    git = shutil.which("git")
    if git is None:
        return "The store is a Git repository but Git was not found, so nothing was committed."
    relative = [str(path.relative_to(store)) for path in paths]
    try:
        subprocess.run(
            [git, "add", "--", *relative], cwd=store, check=True, capture_output=True, text=True
        )
        staged = subprocess.run(
            [git, "diff", "--cached", "--quiet"], cwd=store, capture_output=True, text=True
        )
        if staged.returncode == 0:
            return None  # nothing changed
        subprocess.run(
            [git, "commit", "-m", message], cwd=store, check=True, capture_output=True, text=True
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        return f"The run is saved, but the Git commit failed: {detail.strip()}"
    return None
