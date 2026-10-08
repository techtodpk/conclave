#!/bin/sh
# Conclave installer for macOS and Linux.
#
# Run this in Terminal (no administrator rights needed):
#   curl -LsSf https://raw.githubusercontent.com/techtodpk/conclave/main/install.sh | sh
#
# It installs uv (a small tool that downloads its own private Python), installs Conclave
# with it, puts a Conclave launcher on your desktop, and opens the app. Nothing is
# installed system-wide. To remove Conclave later, see the setup guide.

set -eu
SOURCE="${CONCLAVE_SOURCE:-https://github.com/techtodpk/conclave/archive/refs/heads/main.zip}"
say() { printf '\n\033[36m%s\033[0m\n' "$1"; }

say "Installing Conclave. This takes one or two minutes the first time."

say "Step 1 of 3: getting uv, which keeps a private copy of Python for Conclave"
PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
export PATH
if ! command -v uv >/dev/null 2>&1; then
    if command -v curl >/dev/null 2>&1; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    else
        wget -qO- https://astral.sh/uv/install.sh | sh
    fi
fi
command -v uv >/dev/null 2>&1 || { echo "uv could not be installed. Check your internet connection and try again." >&2; exit 1; }

say "Step 2 of 3: installing Conclave"
uv tool install --force --python 3.13 "conclave-council[app,mcp] @ $SOURCE"
uv tool update-shell >/dev/null 2>&1 || true
BIN="$(uv tool dir --bin)"

say "Step 3 of 3: adding a Conclave launcher to your desktop"
"$BIN/conclave" shortcut || echo "(No desktop launcher was made; start Conclave with: conclave app)"

say "Done. Conclave is opening in your browser."
echo "Next time, open the Conclave launcher on your desktop, or run: conclave app"
echo "Conclave runs while this window is open; close it, or press Ctrl+C, to stop Conclave."
if [ -z "${CONCLAVE_NO_LAUNCH:-}" ]; then
    exec "$BIN/conclave" app
fi
