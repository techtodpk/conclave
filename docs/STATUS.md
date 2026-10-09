# Project status

**The single source of truth for what Conclave does today, what is being built now, and what is still to come.** Every change that adds, removes or changes a capability updates this file in the same commit.

Last updated: 10 October 2026 · Version 0.7.0 · Latest tag: `milestone-7`

| | |
| --- | --- |
| **Done** | Milestones 1 to 5 and 7: project setup; asking one model or a whole council; members reviewing each other and a chairman's one-page answer; a memory per topic that each new question starts from; web search, with key claims checked against the cited pages; an app in the browser with a one-command install and guided setup |
| **In progress** | Milestone 6: the MCP server, built and awaiting its live run in Claude Desktop |
| **Next** | Milestone 8: running members on your own Claude, Gemini or ChatGPT plan, and a sample topic |

## Scope

Conclave sends one question to several LLMs, has them critique each other, checks their key claims, and saves a one-page answer to a research store on the user's own machine. Every later question on that topic starts from what was already worked out. The reasons behind each design choice are in [decisions](decisions/).

| In scope for v1 | Out of scope for v1 |
| --- | --- |
| A local app in the browser, with a guided setup, on Windows, macOS and Linux (decision 0013) | A hosted web service |
| Command-line tool | Mobile apps |
| Council members, chairman and checker chosen by the user | Logging in to chat web apps with stored passwords |
| Cross-critique, claim checking and web search on full runs | Vector database or embeddings |
| A local research store in plain files, with full-text search | Reading the store from the ChatGPT app |
| An MCP server for Claude Desktop and Cursor | Multiple users or cloud sync |
| Optional routes through the user's own subscription CLIs | Any server run by this project |

A change of scope is recorded as a decision record before it is built.

## Milestones

| # | Milestone | Status | Tag |
| --- | --- | --- | --- |
| 1 | Repo setup | Done, 7 Oct 2026 | `milestone-1` |
| 2 | Council core | Done, 8 Oct 2026 | `milestone-2` |
| 3 | Critique and chairman | Done, 8 Oct 2026 | `milestone-3` |
| 4 | Store and recall | Done, 8 Oct 2026 | `milestone-4` |
| 5 | Web search and claim check | Done, 8 Oct 2026 | `milestone-5` |
| 6 | MCP server | Built, awaiting live run | |
| 7 | App and guided install | Done, 10 Oct 2026 | `milestone-7` |
| 8 | CLI adapters and showcase | Pending | |
| 9 | Public ranking chart | Pending | |

A milestone is done when every task below is ticked, the tests and CI pass, it has been run against the live API, and the README, setup guide, changelog and this file describe it.

### 1. Repo setup: done

- [x] Public repository under the MIT licence
- [x] README stating the gap this project fills
- [x] `conclave init` and `conclave config`
- [x] TOML configuration with validation, three starting profiles and budget caps
- [x] Design document and decision records
- [x] Setup guide for Windows, macOS and Linux
- [x] CI on three operating systems, with a secret scan
- [x] Ignore rules for keys and research folders, guarded by a test

### 2. Council core: done

- [x] Model client for OpenRouter, with retries and plain-language errors
- [x] API key read from the environment or a `.env` file, never printed or saved
- [x] `conclave models`: available models with live prices
- [x] `conclave profile add`: build a council, with every model id checked against the live list
- [x] `conclave ask`: quick mode (chairman only) and `--full` (every member at once)
- [x] Each run saved as plain files: question, one answer per model, tokens, cost and timings
- [x] Budget caps checked before anything is sent; monthly cap pauses full runs
- [x] One member failing never loses the others' answers
- [x] `python -m conclave` for terminals where the command is not on PATH
- [x] Run against the live API: quick run $0.012, three-member research run $0.020

### 3. Critique and chairman: done

Done when a full run ends with a one-page answer that shows what the members agreed on and where they disagreed, and every member's ranking of the others is saved.

- [x] Critique prompt: each member reviews the others' answers under hidden names (A, B, C), noting errors and omissions
- [x] Each member ranks the other answers; rankings saved to `rankings.json`
- [x] Rankings read reliably even when a model formats them loosely; unreadable rankings recorded, not guessed
- [x] Chairman prompt: the one-page answer, with sections for the answer, what was agreed, what was disputed, and open questions
- [x] Every key claim on the page labelled "agreed but unchecked", "disputed" or "single model" ("verified" arrives with claim checking in milestone 5)
- [x] `final.md` saved in the run folder and printed at the end of a full run
- [x] Budget cap checked again before each stage; a run that would exceed it stops and keeps what it has
- [x] A stage failing keeps the earlier stages' output
- [x] Tests against the simulated API
- [x] Live run of a full question: $0.066, all three rankings readable
- [x] `--chairman` option to pick a different chairman for one run
- [x] `--chairman` option built for the comparison; the comparison itself moved to follow-ups

### 4. Store and recall: done

Done when a follow-up question on a topic uses what earlier runs concluded, and the memory's changes can be seen and undone.

- [x] Topic files: `summary.md`, `disputes.md` and `notes.md`, written from `memory.json` (decision 0010)
- [x] Recall: the topic's claims, open disputes and notes are given to the members and the chairman, on quick and full runs
- [x] Summary held as a list of claims and updated by patch, never rewritten whole (decision 0006)
- [x] Only agreed or verified claims enter the summary; disputed ones go to `disputes.md`; the rules are enforced in code
- [x] Each full run's `final.md` ends with what changed in memory
- [x] One Git commit per run and per note when the store is a Git repository
- [x] `--review` to approve memory changes before they are saved; `--fresh` to ignore the memory for one run
- [x] Full-text search index (SQLite FTS5), rebuilt from the files whenever they change
- [x] `conclave search`, `conclave topics`, `conclave show` and `conclave note`
- [x] `conclave leaderboard`: which model the others ranked highest, overall and per topic
- [x] Tests against the simulated API
- [x] Before each run, the key's remaining OpenRouter credit is checked against the run's worst-case cost; the balance is printed after the run
- [x] Room for hidden reasoning on every call, `run.reasoning` setting, and cut-off texts detected, marked and kept out of memory
- [x] Live run: two related full questions on topic `os`. The second recalled 6 claims and 3 disputes, then added 3 claims, refined 1 and resolved 2 disputes. $0.097 and $0.090
- [x] `sources.md`: moved to milestone 5, since there are no sources to record until web search exists
- [ ] `conclave rebuild <topic>`: moved to follow-ups (decision 0010)

### 5. Web search and claim check: done

Done when members cite live sources and the key claims on the final page are checked against them.

- [x] Members search the web for themselves through OpenRouter's web search tool on the Exa engine, up to 3 searches per answer; `--no-search` and `[search]` in the config turn it off (decisions 0007 and 0011)
- [x] Key claims picked by the checker, with the sources behind them; it can only name sources members cited
- [x] Source overlap check in code: a claim whose members all lean on one website is labelled "single source" (decision 0005)
- [x] Cited pages fetched on your machine, falling back to the search excerpt; the checker gives each key claim a verdict, which counts only if its quote is in the page
- [x] Labels worked out in code and given to the chairman; "verified" enters memory only for a claim the checker verified
- [x] `verification.md` and `verification.json` in each run; a Sources section on the final page
- [x] `sources.md` per topic, and `sources.json` per run: every page cited, whether it was fetched, and what it checked
- [x] Each run logs searches, distinct sources, pages fetched and the share of checked claims verified
- [x] Pre-run cost ceiling includes searches, search results and checking; default full-run cap raised to $1.00
- [x] Tests against a simulated API and a simulated web
- [x] First live run, topic `os`: 11 pages cited, 7 fetched, 5 of 8 key claims verified against python.org and the free-threading guide, D1 resolved, $0.17. Gemini's search failed (HTTP 504) and it dropped out; fixed by answering without search
- [x] Second live run after the fixes: all three members answered after 1, 5 and 2 searches, 17 pages cited, 4 of 8 key claims verified, $0.28. Search fees are included in the cost OpenRouter reports
- [x] Budget caps reviewed against measured costs: full runs with search cost $0.17 and $0.28 against a $0.59 ceiling, so the $1.00 default cap stands
- [ ] `--deep`: moved to follow-ups (decision 0011)

### 6. MCP server: built, awaiting live run

Done when Claude Desktop and Cursor can both search the store and start a run.

- [x] Tools: `search_research`, `get_topic`, `ask_council` and `add_note`, plus `list_topics` and `get_run` (decision 0012)
- [x] Runs over stdio with the official MCP Python SDK (version 2), installed as the optional extra `.[mcp]`; started with `conclave mcp`
- [x] `ask_council` is quick by default and full only when asked; every check the command line makes applies, from one shared module
- [x] Notes added through MCP are marked with the client's name
- [x] Tests: every tool in process, and a real stdio session started as a client would
- [x] Setup steps for Claude Desktop and Cursor in the setup guide
- [ ] Live run: Claude Desktop reads the `os` topic and starts a quick run
- [ ] Live run: Cursor connects and lists the tools

### 7. App and guided install: done

Done when someone who has never used a terminal can install Conclave from one copied command, finish setup in the browser, and get a full council answer. Decision 0013.

- [x] `conclave app`: a local web app on `127.0.0.1`, opened in the browser; a second launch reuses the running app
- [x] Setup wizard on first launch: research folder, key checked with OpenRouter, council, spending limits, a first question
- [x] Ask, quick or full, with every stage, call, cost and source shown live
- [x] Topics with claims, labels, history and disputes; notes added and removed; every run in full, including claim checks and sources
- [x] Search, spending by month and run, and the model leaderboard
- [x] Settings: key, defaults, spending limits, web search, advanced options, and councils built from OpenRouter's live model list with prices
- [x] Protection: local host names only, a required request header, other sites' origins refused, model output rendered without raw HTML
- [x] Config edits keep the user's comments and never write an invalid file
- [x] `install.ps1` and `install.sh`: uv, Conclave with its private Python, a desktop shortcut, then the app; no Git, Python or administrator rights needed
- [x] Tests: the API end to end against the simulated OpenRouter, config editing, shortcuts and installers; the installer run in a clean home folder on Linux; every page checked in a browser in light, dark and phone widths
- [x] Project website on GitHub Pages, from `docs/index.html`: what Conclave does, how far to trust each claim, screenshots, install commands and measured costs
- [x] "Try it in your browser" through GitHub Codespaces (`.devcontainer`): the app starts by itself and trusts only that Codespace's own forwarded address
- [x] GitHub Pages turned on; the site at techtodpk.github.io/conclave checked: every section, screenshot, menu link and install command
- [x] Code on GitHub matches the tested code (installers, devcontainer, site, app, docs)
- [x] Live run on Windows: installed with the one-line command from GitHub (`conclave 0.7.0`), setup wizard finished from an empty config with the key checked live
- [x] Live run on Windows: a full question from the app, four members, 24 sources, 8 claims checked and 3 verified, 107 s, $0.29
- [x] A model that spends its whole limit thinking is asked once more with reasoning off, and both attempts are counted in the cost. In the live run DeepSeek's review was lost this way
- [x] Desktop shortcut opens the app on Windows
- [ ] Live run on macOS: moved to follow-ups
- [ ] "Try it in your browser" in a live Codespace: moved to follow-ups

### 8. CLI adapters and showcase: pending

Done when a full run works with Claude on the user's own plan, and the README shows a real sample topic with its numbers.

- [ ] Adapters for `claude -p`, Gemini CLI and Codex CLI, chosen per model with `route = "cli"` (decision 0001)
- [ ] Every adapter can fall back to the API through a config change
- [ ] CLI calls counted and logged, though they cost nothing against the caps
- [ ] A sample topic folder in the repository
- [ ] Measured cost and time per run published in the README

### 9. Public ranking chart: pending

Done when the chart shows at least one public source beside the personal leaderboard, each with its date, link and attribution.

- [ ] `conclave rank`: one row per model, one column per source, price beside it (decision 0003)
- [ ] Artificial Analysis first, then LMArena, LiveBench and DeepSWE
- [ ] Model-name mapping file
- [ ] Licences of LiveBench and DeepSWE checked before use

## Known issues and follow-ups

| Item | Detail | Planned |
| --- | --- | --- |
| Chairman can also be a member | In the first live run the chairman, Claude Sonnet 5.5, also wrote response A, which the peer ranking put first. The chairman sees letters, not names, but may still favour its own model's answer | Compare chairmen with `--chairman` on a few questions, then decide whether the default chairman should come from outside the members |
| Duplicate claims in memory | The memory update can add a claim that repeats one it just changed: on topic `os`, new C8 repeats the caveat added to C6 | Milestone 5: the memory prompt now says to change rather than add; code refuses near-identical claims and flags likely repeats as "may repeat C6". Word overlap is a rough guide, so watch for misses |
| Reviewers can be confidently wrong | A reviewer said PEP 779 does not exist; it does, and it set the criteria under which Python 3.14 supports free-threading. The chairman then called the correct citation unreliable | Claim checking built in milestone 5; the live run should settle D1 on topic `os` |
| Settled disagreements stored as open disputes | When reviewers outvote a claim and the chairman settles it on the page, the memory update can still open it as a dispute (D2 and D3 on topic `os`; the next run resolved both) | Milestone 5: the memory prompt now says not to open a dispute the page settles. Watch in live runs |
| CI results for milestone 2 unconfirmed | The milestone 2 run took 10.5 minutes and its secret scan passed, but the test job results have not been checked | Check on the Actions page |
| Cost estimate is a ceiling | The pre-run check assumes every model writes the longest answer allowed and uses every search, so it can refuse runs that would have cost less. A `balanced` full run's ceiling is about $0.59; measured runs with search cost $0.17 and $0.28 | Keep; revisit if it refuses runs that would have fitted |
| Search limit not always kept | With a limit of 3 searches per answer, GPT-6.1 Sol ran 5 in the second live run. OpenRouter billed it $0.014 in search fees, so the cost was small, and the pre-run ceiling has room for it | Check whether the limit belongs elsewhere in the request; until then the ceiling is an estimate |
| Full runs inside one tool call | A full `ask_council` call takes one to two minutes. A client that times out tool calls sooner shows an error, though the run still finishes and is saved | Check in the milestone 6 live run; if needed, report progress or return early and let the assistant fetch the result with `get_run` |
| Installer is unsigned | The one-line installer is a script the user runs on trust, like uv's own installer | A signed `.exe` and `.dmg` later, on top of the same steps |
| `--deep` devil's advocate | One low-cost model argues against the consensus and the chairman answers its strongest point (decision 0005) | Moved from milestone 5; not scheduled |
| `conclave rebuild <topic>` | Regenerate a topic's summary from all its runs and show how it differs from the current one, as a drift check. Deferred until topics have enough runs to drift | After milestone 5 |
| Installer not yet run on macOS | `install.sh` is tested in a clean home folder on Linux, and the Windows installer live; neither has run on a Mac | Run it on a Mac when one is available |
| Codespace not yet opened for real | The `.devcontainer` configuration is checked, but no live Codespace has been opened from the README link | Open one and check the app loads |
| A member may choose not to search | In the milestone 7 live run Claude Sonnet answered without searching, so none of its claims could be checked against a page. The model decides whether to search (decision 0011) | Watch; if it recurs, require at least one search on full runs |
| A retry can go past the cost ceiling | Asking again with reasoning off adds a call the pre-run estimate does not count. It happens only after a failed attempt and costs about one call | Keep; the cap is checked again before each stage |
| No interactive model picker | Profiles are built with `conclave profile add`; an interactive picker may come later | Not scheduled |

## How to keep this file current

- A change that adds or changes a capability ticks its task here, updates the README's [what works today](../README.md#what-works-today) table, and adds a line to the [changelog](../CHANGELOG.md), in the same commit.
- A new task goes under its milestone. Work that fits no milestone goes in "Known issues and follow-ups".
- When a milestone is done, update the summary at the top, the milestones table and its tag.
