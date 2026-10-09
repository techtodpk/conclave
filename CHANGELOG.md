# Changelog

Each milestone on the [roadmap](README.md#roadmap) is tagged in Git when it is complete. Work in progress and pending tasks are tracked in [project status](docs/STATUS.md).

## Milestone 7: app and guided install, 10 October 2026

Version 0.7.0. Tagged `milestone-7`. Live run on Windows: installed with the one-line command from GitHub, setup wizard finished from an empty config, a full four-member question answered in the app ($0.29, 3 of 8 claims verified), and the desktop shortcut opens the app. Not yet run on macOS or in a live Codespace. Decision record [0013](docs/decisions/0013-local-app-and-guided-install.md) moves a web interface into the scope of v1; the later milestones are renumbered (CLI adapters and showcase are now 8, the public ranking chart 9).

- `conclave app` opens Conclave in your browser. It runs on your own computer at `http://127.0.0.1:8765` and answers only to pages from it. Starting it again while it is running just opens the page.
- A setup wizard on first launch: research folder, OpenRouter key (checked with OpenRouter before it is saved, and never shown again), council, spending limits, and a first question.
- Ask a question, quick or full, and watch each stage, model call, cost and source as it happens. The one-page answer shows claim labels as coloured badges.
- Topics: claims with their labels and earlier wording, open and resolved disputes, your notes (add and remove), and every run. A run shows the one-page answer, each member's answer and review, the claim checks, the sources and the cost of every call.
- Search, spending by month and by run against your limits, and the model leaderboard.
- Settings: the key, default council and thoroughness, spending limits, web search, advanced options, and councils built by picking models from OpenRouter's live list with their prices.
- One-command installers, `install.ps1` for Windows and `install.sh` for macOS and Linux. They install uv, which keeps a private copy of Python, install Conclave with the app and MCP extras from GitHub's zip download, add a desktop shortcut (`conclave shortcut`), and open the app. No Python, Git or administrator rights are needed.
- The app's packages are the optional extra `.[app]`. The command line still needs only two packages.
- Config changes from the app are small edits that keep your comments; a change that would make the config invalid is refused before it is written. The key is saved in `.env` beside the config.
- A model that spends its whole length limit on hidden reasoning and writes nothing is asked once more with reasoning off, instead of being dropped. Both attempts are counted in the cost, and the run record, the app and the command line say it was asked again.
- The runner reports progress as it goes, for the app: each stage, each model call as it starts and finishes, and the claim-checking steps.
- The setup guide starts with a section for people who do not use a terminal, with screenshots.
- A project website at techtodpk.github.io/conclave, served free by GitHub Pages from `docs/index.html`.
- "Try it in your browser": a GitHub Codespaces configuration that installs Conclave and opens the app. It runs on the visitor's own free Codespaces allowance. Inside a Codespace, and only there, the app also trusts that Codespace's forwarded web address.

## Milestone 6: MCP server, 10 October 2026

Version 0.7.0; the MCP server first shipped in 0.6.0. Tagged `milestone-6` after its live run in Claude Desktop on Windows: listing topics, answering from a topic's claims, a quick run, a marked note, and a 70-second full run within one tool call ($0.22). Not yet tried in Cursor.

- `conclave mcp` runs Conclave as an MCP server over stdio, so Claude Desktop, Cursor and other MCP clients can use the research store. It needs the optional extra: `python -m pip install -e ".[mcp]"`.
- Six tools: `list_topics`, `search_research`, `get_topic` and `get_run` read the store; `ask_council` runs a question; `add_note` adds a note.
- `ask_council` runs a quick run unless the assistant asks for a full one. Every check the command line makes applies to it, including the per-run and monthly caps and the key's credit, because both now share one module for planning and running a question.
- Notes added through MCP end with "(added by <client> via MCP)", so they can be told apart from your own.
- The setup guide has a new step 10 with the config for Claude Desktop and Cursor on Windows and macOS. Later steps are renumbered.
- Decision record [0012](docs/decisions/0012-mcp-server.md).
- Setup step 10 gives the shorter config for people who used the installer: the installed `conclave` command with `"args": ["mcp"]`.
- Every member now searches at least once in a full run. Claude Sonnet had stopped searching, because the prompt told members not to search for what they know well, so none of its claims could be checked. The prompt now requires a search, and a member that still answers without searching or citing a page is asked once more to search; both calls are counted in the cost, and the run says so. Decision 0011 has an addendum.

## Milestone 5: web search and claim check (2026-10-08)

Tag: `milestone-5`. Version 0.5.0.

- Members search the web in full runs. Each decides what to search for, up to 3 searches per answer, through OpenRouter's web search tool on the Exa engine (about $0.007 per search), and cites the pages it used. Quick runs do not search. `--no-search` or `[search] enabled = false` answers from training data alone.
- A new Verify stage between Critique and Synthesis. The profile's checker picks up to 8 key claims from the answers and reviews, preferring disputed claims and claims resting on one source. Conclave fetches the pages cited for them on your machine and gives the checker the passages that bear on each claim; when a page cannot be fetched, the search excerpt is used and the verdict says so. The checker says supported, contradicted or not found for each.
- Code, not the model, decides what counts: a verdict stands only if the words it quotes are in the page, and each claim's label (verified, agreed but unchecked, single source, single model, disputed) is worked out from the verdict and from how many members and websites back it. The chairman is given these labels and told to use them.
- A claim enters memory as "verified" only if it matches one the checker verified in that run.
- New files: `verification.md` and `verification.json` (every checked claim, its verdict, quote and label), `sources.json` in each run, and `sources.md` in each topic (every page cited, by run, whether it was fetched and what it checked). The final page lists its sources and says what was checked.
- The report shows each member's searches and citations, and an Evidence line.
- `meta.json` records searches, distinct sources, pages fetched and the share of checked claims verified.
- The pre-run cost ceiling includes searches, the search results models read, and checking. The default full-run cap rose from $0.75 to $1.00; an existing config keeps its own.
- Reviews are named by the response their author wrote ("the review by B's author"), not by number.
- The memory update is told to change a claim rather than add a near-copy, and not to open a dispute the page has settled. Code refuses a claim that repeats an existing one and flags a likely repeat as "may repeat C6".
- A full run now makes 2N + 3 model calls for N members.
- Decision record [0011](docs/decisions/0011-web-search-and-claim-checking.md). The devil's advocate pass (`--deep`) moved to follow-ups.
- Fixed after the first live run:
  - When the search service fails for a member, it now answers without searching instead of dropping out, and the run says so. A provider error reported inside an HTTP 200 reply, and HTTP 504, are retried like other busy-provider errors.
  - The number of searches is shown only when OpenRouter reports it; it is no longer shown as 0. Each call's usage figures, as OpenRouter sent them, are saved in `meta.json`.
  - A checker's quote must come from one stretch of a page, not join words across a gap; neighbouring parts of a page are joined without a gap.
  - A claim stored as verified may not add detail the checked claim did not have.
  - The checker is told not to pick two claims that one sentence would settle.
  - The key-balance comparison was removed: OpenRouter updates the balance some time after a run.
- Fixed after the second live run: the search count is read from where OpenRouter reports it (`server_tool_use_details`); links that differ only by a tracking parameter such as `?featured_on=` count as one page; the passages given to the checker keep each part of a page whole instead of cutting it mid-sentence.
- Checked against the live OpenRouter API on Windows, on topic `os`. The first run resolved an open dispute from an earlier run against Python's own documentation: 5 of 8 key claims verified, $0.17. The second, after fixes, had all three members search (1, 5 and 2 searches) and cite 17 pages; 4 of 8 key claims verified, $0.28. Search fees are included in the cost OpenRouter reports.

## Milestone 4: store and recall (2026-10-08)

Tag: `milestone-4`. Version 0.4.0.

- Each topic keeps a memory: the claims the council concluded, open disputes, and your own notes. It is read before every question on the topic, quick or full, and given to the members and the chairman.
- After a full run the chairman proposes changes to the memory, and code applies them under fixed rules: a claim is added only if the members agreed on it; "single model" and "disputed" points never enter as claims, and disputed ones become disputes; a claim is changed or retired only with a reason; nothing is deleted; claim and dispute ids are never reused.
- `final.md` ends with "What changed in memory". `memory_patch.json` records what was proposed, applied and refused, and `recall.md` what the council was given.
- `--review` shows the proposed changes and asks before saving them. `--fresh` ignores the memory for one run and leaves it unchanged.
- `memory.json` is the record; `summary.md` and `disputes.md` are written from it. `notes.md` is yours and only ever appended to.
- If the research store is a Git repository, every run and note is committed.
- New commands: `conclave topics`, `conclave show <topic>`, `conclave note <topic> "..."`, `conclave search "..."` and `conclave leaderboard`.
- Search uses a SQLite full-text index, rebuilt from the files whenever they change; it is never the source of anything.
- The leaderboard scales each place from 0 (ranked best) to 1 (ranked worst), so councils of different sizes can be compared.
- The pre-run budget check now includes the memory update.
- Before each run, Conclave asks OpenRouter how much credit the key has left, and refuses the run if its worst-case cost is higher, so nothing is sent that the key cannot pay for. A key with no limit, or a balance that cannot be read, does not block the run. After a run the key's remaining balance is printed.
- A clearer message when OpenRouter refuses a call for lack of credit (HTTP 402), pointing to the key's limit.
- `show` and `topics` read each run's mode from `meta.json`, so a full run that stopped early is no longer listed as quick.
- Answers are no longer cut short by hidden reasoning. Reasoning models think before they answer, and that thinking counts against the length limit: in the first live runs Claude Sonnet and Gemini used more than half of it thinking, so answers, a review and the memory update ended mid-sentence. Every call now gets 2,048 tokens of room for reasoning on top of the answer, and a new setting, `run.reasoning` (default `low`), sets how hard models think.
- A text that still reaches the length limit is marked `CUT OFF` in the report and `cut_off` in `meta.json`, which also records reasoning tokens. Reviewers and the chairman are told which texts were cut off, and a memory update that was cut off is never applied.
- The pre-run cost ceiling now includes the reasoning room, and the default quick-run cap rose from $0.05 to $0.10 so a quick run with the `full` profile's Opus chairman still fits. An existing config file keeps its own caps.
- Fixed before release: on Windows, rebuilding the search index failed because a database connection was left open. Every connection is now closed explicitly, and a test fails if one is left open.
- Checked against the live OpenRouter API on Windows: two related full runs on one topic. The first ($0.097) stored 6 claims and 3 disputes. The second ($0.090) recalled them, added 3 claims, refined 1 and resolved 2 disputes. No text was cut off.

## Milestone 3: critique and chairman (2026-10-08)

Tag: `milestone-3`. Version 0.3.0.

- A full run now has three stages: every member answers, every member reviews the others' answers with the authors hidden behind letters and ranks them, and the chairman writes a one-page answer.
- The one-page answer, `final.md`, has the answer, the key claims each labelled "agreed but unchecked", "single model" or "disputed", the disagreements, and open questions. It ends with which model wrote which response and the average peer ranking of each.
- Reviews are saved in `critiques/`, and every ranking in `rankings.json`. A ranking not written in the expected form is recorded as unreadable and left out of the averages, never guessed.
- Reviewers never see their own answer. The chairman sees response letters, not model names.
- `--chairman <model id>` picks a different chairman for one run.
- The budget check before a full run now covers all three stages. Each later stage is checked again before it starts, and a run that would go over its cap stops and keeps what it has.
- If only one member answers, the review and the one-page answer are skipped. If the chairman fails, the answers and reviews are kept.
- `meta.json` lists every call with its stage.
- CI moved to current action versions on Node.js 24, and tests Python 3.11 and 3.14.
- Checked against the live OpenRouter API on Windows: a full run with three members, three reviews and the chairman's page cost $0.066, and all three rankings were readable.

Documentation since milestone 2:

- README: a "what works today" table, measured costs from the first live runs, and corrected descriptions of stages that are not built yet.
- New [project status](docs/STATUS.md) page: scope, every milestone's tasks with what is done and pending, and known issues.

## Milestone 2: council core (2026-10-08)

Tag: `milestone-2`. Version 0.2.0.

- `conclave ask "question"` asks the council and saves every answer to the research store. Quick mode asks the chairman; `--full` asks every member at the same time. `--topic` files the run under a topic, `--profile` picks a council, and `--members` asks a one-off set of models.
- Each run is saved as plain files: `question.md`, one answer file per model, and `meta.json` with tokens, cost and timings.
- Answers follow one structure: the answer, the key claims it depends on with a confidence for each, and what the model is unsure of.
- `conclave models` lists available models with live prices, with `--search`, `--vendor`, `--sort` and `--limit`.
- `conclave profile add` adds a council profile to the config after checking every model id against the live list.
- Budget caps are enforced. The worst-case cost of a run is worked out before anything is sent, and the run is refused if it is above the cap. Full runs pause when the month's recorded spending reaches the monthly cap.
- The API key is read from the environment or a `.env` file, and is never printed or stored.
- One member failing never loses the others' answers. Rate limits and provider errors are retried twice.
- New setting `run.max_answer_tokens` (default 1500).
- `python -m conclave` works the same as the `conclave` command, for terminals where the command is not on PATH.
- When no API key is found, the message says what was found in each place checked, including a `.env.txt` that Notepad may have created. Key files saved by Windows editors with a byte-order mark or as UTF-16 are read correctly.
- Tests run against a simulated OpenRouter: no key, no cost, no network.
- Checked against the live OpenRouter API on Windows with Python 3.14: a quick run cost $0.012, and a full research run with three members cost $0.020.

Not yet available: cross-critique between models and the one-page synthesis, which arrive in milestone 3. Web search arrives in milestone 5, so answers in this milestone come from the models' training data.

## Milestone 1: repo setup (2026-10-07)

Tag: `milestone-1`. Version 0.1.0.

- `conclave init` creates the config file and the research store, and never overwrites either.
- `conclave config` shows the store location, the budget caps and every profile, and warns when two members of a profile share a vendor.
- Configuration in one TOML file with validation and clear error messages. Three starting profiles: `lean`, `balanced` and `full`.
- Budget caps in the config: per full run, per quick run and per month.
- README with the gap comparison, the six-stage flow, cost, privacy and the roadmap.
- [Setup guide](docs/SETUP.md) for Windows, macOS and Linux.
- [Design](docs/design.md) and seven [decision records](docs/decisions/).
- MIT licence.
- Ignore rules for keys and research folders, with a test that fails if they are removed.
- CI on Windows, macOS and Linux for Python 3.11 and 3.13: lint, format check, tests and a secret scan.

Not yet available: asking questions (`conclave ask`), which arrives in milestone 2.
