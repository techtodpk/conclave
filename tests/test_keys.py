import pytest

from conclave.keys import MissingKeyError, load_api_key, read_env_file


def test_environment_variable_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", " from-env ")
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=from-file\n", encoding="utf-8")

    assert load_api_key(tmp_path / "config.toml", cwd=tmp_path) == "from-env"


def test_env_file_in_the_working_folder_is_used(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    work, settings = tmp_path / "work", tmp_path / "settings"
    work.mkdir()
    settings.mkdir()
    (work / ".env").write_text("OPENROUTER_API_KEY=from-work\n", encoding="utf-8")
    (settings / ".env").write_text("OPENROUTER_API_KEY=from-settings\n", encoding="utf-8")

    assert load_api_key(settings / "config.toml", cwd=work) == "from-work"


def test_env_file_beside_the_config_is_the_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    settings = tmp_path / "settings"
    settings.mkdir()
    (settings / ".env").write_text("OPENROUTER_API_KEY=from-settings\n", encoding="utf-8")

    assert load_api_key(settings / "config.toml", cwd=tmp_path) == "from-settings"


def test_an_empty_value_counts_as_missing(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path / ".env").write_text("OPENROUTER_API_KEY=\n", encoding="utf-8")

    with pytest.raises(MissingKeyError) as raised:
        load_api_key(tmp_path / "settings" / "config.toml", cwd=tmp_path)

    message = str(raised.value)
    assert str(tmp_path / ".env") in message
    assert str(tmp_path / "settings" / ".env") in message
    assert "openrouter.ai/keys" in message


def test_env_file_parsing(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# a comment\n\nexport A=1\nB = 'two words'\nC=\"three\"\nnot a pair\nD=x=y\n",
        encoding="utf-8",
    )

    assert read_env_file(env) == {"A": "1", "B": "two words", "C": "three", "D": "x=y"}
    assert read_env_file(tmp_path / "absent") == {}


def test_byte_order_mark_from_windows_editors_is_ignored(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path / ".env").write_bytes(b"\xef\xbb\xbfOPENROUTER_API_KEY=with-bom\r\n")

    assert load_api_key(tmp_path / "settings" / "config.toml", cwd=tmp_path) == "with-bom"


def test_utf16_file_saved_as_unicode_is_read(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    (tmp_path / ".env").write_bytes("OPENROUTER_API_KEY=utf16-key\r\n".encode("utf-16"))

    assert load_api_key(tmp_path / "settings" / "config.toml", cwd=tmp_path) == "utf16-key"


def test_missing_key_message_explains_each_location(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    work, settings = tmp_path / "work", tmp_path / "settings"
    work.mkdir()
    settings.mkdir()
    (work / ".env").write_text("SOMETHING_ELSE=secret-value\n", encoding="utf-8")
    (settings / ".env.txt").write_text("OPENROUTER_API_KEY=hidden\n", encoding="utf-8")

    with pytest.raises(MissingKeyError) as raised:
        load_api_key(settings / "config.toml", cwd=work)

    message = str(raised.value)
    assert "exists, but has no OPENROUTER_API_KEY" in message
    assert ".env.txt is there. Rename it to .env" in message
    assert "secret-value" not in message
    assert "hidden" not in message
