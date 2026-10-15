"""Guards for the public-repo safeguards: research and keys must never be committed."""

from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def _ignored_patterns() -> set[str]:
    lines = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def test_secrets_and_research_are_ignored():
    patterns = _ignored_patterns()

    assert ".env" in patterns
    assert "research/" in patterns
    assert "conclave-research/" in patterns


def test_env_example_holds_no_real_key():
    for line in (REPO / ".env.example").read_text(encoding="utf-8").splitlines():
        if line.startswith("OPENROUTER_API_KEY"):
            assert line.strip() == "OPENROUTER_API_KEY="


def test_examples_hold_no_private_details():
    """The sample topics are public: no local paths, keys, sessions or redirect links."""
    import re

    forbidden = re.compile(
        r"[A-Za-z]:\\\\|/Users/|/home/|sk-or-|OPENROUTER_API_KEY=\S|session_id|conversation_id"
        r"|thread_id|vertexaisearch\.cloud\.google\.com",
    )
    files = [p for p in (REPO / "examples").rglob("*") if p.is_file()]
    assert files
    for path in files:
        found = forbidden.search(path.read_text(encoding="utf-8"))
        assert found is None, f"{path.relative_to(REPO)}: {found.group(0)}"
