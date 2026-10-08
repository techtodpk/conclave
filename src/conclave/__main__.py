"""Lets `python -m conclave` work when the `conclave` command is not on PATH."""

from conclave.cli import app

if __name__ == "__main__":
    app(prog_name="conclave")
