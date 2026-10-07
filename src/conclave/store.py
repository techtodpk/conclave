"""The local research store: plain files on the user's own disk.

Milestone 1 only creates the folder. Topic folders, runs and the search index
arrive in milestone 4.
"""

from __future__ import annotations

from pathlib import Path

STORE_README = """\
# Conclave research store

This folder is your private research memory. Conclave reads it before every
question on a topic and writes back to it after every full run.

- Keep it out of any public repository.
- Make it its own private Git repository if you want history and backup:
  run `git init` here.
- Everything is plain text. You can read and edit any file yourself.

Layout (filled in as you use Conclave):

    topics/
      <topic>/
        summary.md     current best answer for the topic, one claim per line
        disputes.md    disagreements, each marked open or resolved
        sources.md     every link used, date fetched, check verdict
        notes.md       your own notes; the council reads these too
        runs/          one folder per question, never edited afterwards
"""


def init_store(path: Path) -> list[Path]:
    """Create the store folder if needed. Returns what was created, in order.

    Safe to run again: existing folders and files are left untouched.
    """
    created: list[Path] = []
    topics = path / "topics"
    readme = path / "README.md"

    if not path.exists():
        path.mkdir(parents=True)
        created.append(path)
    if not topics.exists():
        topics.mkdir()
        created.append(topics)
    if not readme.exists():
        readme.write_text(STORE_README, encoding="utf-8")
        created.append(readme)
    return created
