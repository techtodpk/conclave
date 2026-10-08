# 0013: A local app and a one-command install

Date: 2026-10-09. Status: accepted. Changes the scope set in the [design](../design.md): a web interface moves into v1.

## Context

After milestone 6, using Conclave still meant installing Python, opening a terminal, editing a TOML file, putting a key in a `.env` file and typing commands. Only a programmer would do that. The point of the project, a council whose conclusions you keep and build on, is just as useful to someone who has never opened a terminal.

Three kinds of frontend were considered: a desktop app window (a second toolchain to build and sign for each operating system), a dashboard framework such as Streamlit (quick, but it looks like a data tool rather than a product), and a local web app served by Conclave itself. For installing: a signed `.exe` or `.dmg` (friendliest, but it needs code-signing certificates, or Windows SmartScreen and macOS Gatekeeper warn about it), the existing `pip install` (needs Python and a terminal), or one copied command that installs everything, including Python.

## Decision

**A local web app.** `conclave app` serves a page on `127.0.0.1` and opens it in the browser. The page talks to a small JSON API; there is no build step, no Node toolchain and no files fetched from the internet. It covers everything the command line does:

- A setup wizard on first launch: research folder, OpenRouter key (checked with OpenRouter before it is saved), council, spending limits, first question.
- Ask, quick or full, with each stage, call, cost and source shown live as the run happens.
- Topics: claims with their labels and history, disputes, the user's notes (add and remove), runs.
- A run in full: the one-page answer, every member's answer and review, the claim checks, the sources, and the cost of every call.
- Search, spending by month and by run, and the model leaderboard.
- Settings: the key, default council, spending limits, web search, advanced options, and councils built by picking models from OpenRouter's live list with their prices.

**One command to install.** `install.ps1` for Windows and `install.sh` for macOS and Linux:

1. install uv, which downloads its own private copy of Python;
2. `uv tool install` Conclave with the `app` and `mcp` extras, from GitHub's zip download, so Git is not needed;
3. `conclave shortcut` puts a Conclave shortcut on the desktop (and, on Windows, in the Start menu);
4. open the app.

Nothing is installed system-wide and no administrator rights are needed.

**Rules the app keeps:**

- It listens on `127.0.0.1` only. A request must be addressed to a local host name, which stops DNS-rebinding pages. Anything that changes something or spends money must carry an `X-Conclave` header, which a page on another site cannot add, and a request whose `Origin` is another site is refused.
- Every check the command line makes applies, because both go through the same module (decision 0012): budget caps, the monthly cap, the key's credit.
- One question runs at a time.
- Model output is rendered with raw HTML switched off, and only `http` and `https` links are kept. The key is never sent to the page; only its last four characters are shown.
- Config changes are small edits that keep the user's comments, and a change that would make the config invalid is refused before it is written.

**Milestones.** This becomes milestone 7. CLI adapters and the showcase move to 8, and the public ranking chart to 9. Milestone 6 keeps its tasks; its live test in Claude Desktop is still to do.

## Consequences

- The app is the way most people will use Conclave; the command line and the MCP server stay for those who want them.
- The app's packages (Starlette, Uvicorn, markdown-it-py) are an optional extra, `.[app]`, so the command line still installs with two dependencies.
- The installer installs from the `main` branch, so what is pushed there is what new users get.
- An unsigned installer script is copied into a terminal. That is a common pattern (uv and many developer tools install this way), but it asks the user to trust this repository. A signed installer can come later on top of it.
- Notes can now be removed from the app. `notes.md` is still the user's own file; Conclave only appends to it, except when the user removes a note themselves.

## Addendum: website and Codespaces (2026-10-09)

The project website is a single static page, `docs/index.html`, served free by GitHub Pages; `docs/.nojekyll` stops GitHub processing the Markdown documents beside it. A `.devcontainer` lets anyone open Conclave in a GitHub Codespace, billed to their own free allowance, never to the repository owner. Inside a Codespace the app also trusts the one forwarded address GitHub gives that Codespace, read from `CODESPACE_NAME` and `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`; outside one, nothing changes. A shared hosted Conclave was rejected: it would hold everyone's keys and research on one server.

## Sources

- [Installing uv](https://docs.astral.sh/uv/getting-started/installation/)
- [uv tools](https://docs.astral.sh/uv/concepts/tools/)
