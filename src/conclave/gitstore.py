"""Commit memory changes when the research store is a Git repository."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def is_repository(store: Path) -> bool:
    return (store / ".git").exists()


def _own_relative(store: Path, path: Path) -> str | None:
    """A path Conclave may commit, relative to the store, or None when it is not ours.

    Only files under topics/ are committed. A lock file, a price cache, or anything
    outside the store is left alone, including files the user had already staged.
    """
    try:
        relative = path.resolve().relative_to(store.resolve())
    except (OSError, ValueError):
        return None
    if not relative.parts or relative.parts[0] != "topics":
        return None
    if any(part.startswith(".") or part in {"", ".."} for part in relative.parts):
        return None
    return relative.as_posix()


def commit(store: Path, paths: list[Path], message: str) -> str | None:
    """Commit Conclave's own paths. Returns None on success, or why it did not commit.

    Does nothing when the store is not a Git repository. Never raises: a failed commit
    must not lose a run that is already saved. Other staged files are not included.
    """
    if not is_repository(store):
        return None
    git = shutil.which("git")
    if git is None:
        return "The store is a Git repository but Git was not found, so nothing was committed."
    own: list[str] = []
    rejected = False
    for path in paths:
        relative = _own_relative(store, path)
        if relative is None:
            rejected = True
            continue
        if path.exists():
            own.append(relative)
    outside = (
        "The run is saved, but a path outside the research store was not committed."
        if rejected
        else None
    )
    if not own:
        return outside
    try:
        subprocess.run(
            [git, "add", "--", *own], cwd=store, check=True, capture_output=True, text=True
        )
        staged = subprocess.run(
            [git, "diff", "--cached", "--quiet", "--", *own],
            cwd=store,
            capture_output=True,
            text=True,
        )
        if staged.returncode == 0:
            return outside  # nothing of ours changed
        subprocess.run(
            [git, "commit", "-m", message, "--", *own],
            cwd=store,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        detail = getattr(error, "stderr", "") or str(error)
        return f"The run is saved, but the Git commit failed: {detail.strip()}"
    return outside
