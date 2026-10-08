from typer.testing import CliRunner

from conclave import __version__
from conclave.cli import app
from conclave.config import load_config

runner = CliRunner()


def test_version():
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"conclave {__version__}"


def test_init_creates_config_and_store(tmp_path):
    config = tmp_path / "settings" / "config.toml"
    store = tmp_path / "my research"

    result = runner.invoke(app, ["init", "--config", str(config), "--store", str(store)])

    assert result.exit_code == 0, result.output
    assert config.is_file()
    assert (store / "topics").is_dir()
    assert (store / "README.md").is_file()
    assert load_config(config).store_path == store


def test_init_never_overwrites(tmp_path):
    config = tmp_path / "config.toml"
    store = tmp_path / "research"
    runner.invoke(app, ["init", "--config", str(config), "--store", str(store)])
    config.write_text(config.read_text(encoding="utf-8") + "\n# my edit\n", encoding="utf-8")
    (store / "README.md").write_text("mine", encoding="utf-8")

    result = runner.invoke(app, ["init", "--config", str(config), "--store", str(store)])

    assert result.exit_code == 0, result.output
    assert "left unchanged" in result.output
    assert config.read_text(encoding="utf-8").endswith("# my edit\n")
    assert (store / "README.md").read_text(encoding="utf-8") == "mine"


def test_config_shows_caps_and_profiles(tmp_path):
    result = runner.invoke(app, ["config", "--config", str(tmp_path / "absent.toml")])

    assert result.exit_code == 0, result.output
    assert "using built-in defaults" in result.output
    assert "Full run:    0.75" in result.output
    assert "Quick run:   0.10" in result.output
    assert "Month:       15.00" in result.output
    assert "Profile 'balanced' (default)" in result.output
    assert "Warning" not in result.output


def test_config_warns_when_members_share_a_vendor(tmp_path):
    config = tmp_path / "config.toml"
    runner.invoke(app, ["init", "--config", str(config), "--store", str(tmp_path / "r")])
    text = config.read_text(encoding="utf-8")
    config.write_text(text.replace("deepseek/deepseek", "google/deepseek"), encoding="utf-8")

    result = runner.invoke(app, ["config", "--config", str(config)])

    assert result.exit_code == 0, result.output
    assert "more than one member comes from google" in result.output


def test_invalid_config_exits_with_a_clear_message(tmp_path):
    config = tmp_path / "config.toml"
    config.write_text("[store]\npath = 3\n", encoding="utf-8")

    result = runner.invoke(app, ["config", "--config", str(config)])

    assert result.exit_code == 1
    assert "Config problem" in result.output


def test_python_dash_m_conclave_works():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "-m", "conclave", "--version"], capture_output=True, text=True, check=False
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == f"conclave {__version__}"
