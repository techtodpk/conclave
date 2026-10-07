"""The `conclave` command."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer

from conclave import __version__
from conclave.config import (
    Config,
    ConfigError,
    Member,
    default_config_path,
    default_config_text,
    load_config,
)
from conclave.store import init_store

app = typer.Typer(
    help="Conclave: an LLM council that remembers.",
    no_args_is_help=True,
    add_completion=False,
)

ConfigOption = Annotated[
    Path | None,
    typer.Option("--config", help="Config file to use. Default: ~/.conclave/config.toml"),
]

DEFAULT_STORE_LINE = 'path = "~/conclave-research"'


def _show_version(value: bool) -> None:
    if value:
        typer.echo(f"conclave {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool,
        typer.Option(
            "--version", callback=_show_version, is_eager=True, help="Show the version and exit."
        ),
    ] = False,
) -> None:
    """Conclave: an LLM council that remembers."""


def _load(config: Path | None) -> Config:
    try:
        return load_config(config)
    except ConfigError as error:
        typer.echo(f"Config problem: {error}", err=True)
        raise typer.Exit(code=1) from None


@app.command()
def init(
    config: ConfigOption = None,
    store: Annotated[
        Path | None,
        typer.Option("--store", help="Where to keep your research. Default: ~/conclave-research"),
    ] = None,
) -> None:
    """Create the config file and the research store. Safe to run again."""
    config_path = (config or default_config_path()).expanduser()

    if config_path.exists():
        typer.echo(f"Config already exists, left unchanged: {config_path}")
    else:
        text = default_config_text()
        if store is not None:
            # as_posix keeps Windows paths valid inside a TOML string.
            text = text.replace(DEFAULT_STORE_LINE, f'path = "{store.expanduser().as_posix()}"')
        config_path.parent.mkdir(parents=True, exist_ok=True)
        config_path.write_text(text, encoding="utf-8")
        typer.echo(f"Created config: {config_path}")

    settings = _load(config_path)
    created = init_store(settings.store_path)
    if created:
        typer.echo(f"Created research store: {settings.store_path}")
    else:
        typer.echo(f"Research store already exists, left unchanged: {settings.store_path}")

    typer.echo("")
    typer.echo("Next: run `conclave config` to check the settings in effect.")


def _describe(member: Member) -> str:
    return f"{member.model} [{member.route}]"


@app.command("config")
def show_config(config: ConfigOption = None) -> None:
    """Show the settings in effect: store, budget caps and every profile."""
    config_path = (config or default_config_path()).expanduser()
    settings = _load(config_path)

    if config_path.is_file():
        typer.echo(f"Config file:   {config_path}")
    else:
        typer.echo(f"Config file:   none at {config_path} (using built-in defaults)")

    store_state = "exists" if settings.store_path.is_dir() else "not created yet"
    typer.echo(f"Store:         {settings.store_path} ({store_state})")
    typer.echo(f"Default run:   {settings.default_mode} mode, '{settings.default_profile}' profile")
    typer.echo(f"Claims checked per full run: {settings.claims_checked}")
    typer.echo("")
    typer.echo("Budget caps (USD)")
    typer.echo(f"  Full run:    {settings.budget.full_run_usd:.2f}")
    typer.echo(f"  Quick run:   {settings.budget.quick_run_usd:.2f}")
    typer.echo(f"  Month:       {settings.budget.monthly_usd:.2f}")

    for name in sorted(settings.profiles):
        profile = settings.profiles[name]
        marker = " (default)" if name == settings.default_profile else ""
        typer.echo("")
        typer.echo(f"Profile '{name}'{marker}")
        for member in profile.members:
            typer.echo(f"  Member:      {_describe(member)}")
        typer.echo(f"  Chairman:    {_describe(profile.chairman)}")
        typer.echo(f"  Checker:     {_describe(profile.checker)}")
        shared = profile.shared_vendors()
        if shared:
            typer.echo(
                f"  Warning: more than one member comes from {', '.join(shared)}. "
                "Models from one lab tend to share blind spots."
            )


if __name__ == "__main__":
    app()
