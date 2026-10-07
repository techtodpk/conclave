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
