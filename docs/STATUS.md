# Project status

**The single source of truth for what Conclave does today, what is being built now, and what is still to come.** Every change that adds, removes or changes a capability updates this file in the same commit.

Last updated: 8 October 2026 · Version 0.3.0 · Latest tag: `milestone-3`

| | |
| --- | --- |
| **Done** | Milestones 1 to 3: project setup; asking one model or a whole council; members reviewing each other and a chairman's one-page answer |
| **In progress** | Milestone 4: topic memory, so earlier research is read before each new question |
| **Next** | Milestone 5: web search, and checking key claims against the cited pages |

## Scope

Conclave sends one question to several LLMs, has them critique each other, checks their key claims, and saves a one-page answer to a research store on the user's own machine. Every later question on that topic starts from what was already worked out. The reasons behind each design choice are in [decisions](decisions/).

| In scope for v1 | Out of scope for v1 |
| --- | --- |
| Command-line tool, on Windows, macOS and Linux | Web interface |
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
| 4 | Store and recall | In progress | |
| 5 | Web search and claim check | Pending | |
| 6 | MCP server | Pending | |
| 7 | CLI adapters and showcase | Pending | |
| 8 | Public ranking chart | Pending | |

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

### 4. Store and recall: in progress

Done when a follow-up question on a topic uses what earlier runs concluded, and the memory's changes can be seen and undone.

- [ ] Topic files: `summary.md`, `disputes.md`, `sources.md` and `notes.md`
- [ ] Recall stage: the topic's summary, open disputes and notes are given to the council before it answers
- [ ] Summary held as a list of claims and updated by patch, never rewritten whole (decision 0006)
- [ ] Only agreed or verified claims enter the summary; disputed ones go to `disputes.md`
- [ ] Each answer ends with what changed in memory
- [ ] One Git commit per run when the store is a Git repository
- [ ] `--review` flag to approve memory changes before they are saved
- [ ] Full-text search index (SQLite FTS5), rebuildable from the files
- [ ] `conclave search`, `conclave topics` and `conclave show`
- [ ] `conclave leaderboard`: which model the others ranked highest, overall and per topic
- [ ] `conclave rebuild <topic>`: regenerate a summary from all runs and show how it differs

### 5. Web search and claim check: pending

Done when members cite live sources and the key claims on the final page are checked against them.

- [ ] Members search the web for themselves (decision 0007)
- [ ] Key claims extracted with the links behind them
- [ ] Source overlap check: a claim that every member took from one page is marked "single source" (decision 0005)
- [ ] Cited pages fetched, and a checker model gives each key claim a verdict
- [ ] `verification.md` saved, and "verified" labels shown on the final page
- [ ] Each run logs distinct sources and the share of claims verified
- [ ] `--deep`: a devil's advocate pass argues against the consensus
- [ ] Budget caps reset from measured costs of full runs

### 6. MCP server: pending

Done when Claude Desktop and Cursor can both search the store and start a run.

- [ ] Tools: `search_research`, `get_topic`, `ask_council` and `add_note`
- [ ] Runs over stdio with the official MCP Python SDK
- [ ] Setup steps for Claude Desktop and Cursor in the setup guide

### 7. CLI adapters and showcase: pending

Done when a full run works with Claude on the user's own plan, and the README shows a real sample topic with its numbers.

- [ ] Adapters for `claude -p`, Gemini CLI and Codex CLI, chosen per model with `route = "cli"` (decision 0001)
- [ ] Every adapter can fall back to the API through a config change
- [ ] CLI calls counted and logged, though they cost nothing against the caps
- [ ] A sample topic folder in the repository
- [ ] Measured cost and time per run published in the README

### 8. Public ranking chart: pending

Done when the chart shows at least one public source beside the personal leaderboard, each with its date, link and attribution.

- [ ] `conclave rank`: one row per model, one column per source, price beside it (decision 0003)
- [ ] Artificial Analysis first, then LMArena, LiveBench and DeepSWE
- [ ] Model-name mapping file
- [ ] Licences of LiveBench and DeepSWE checked before use

## Known issues and follow-ups

| Item | Detail | Planned |
| --- | --- | --- |
| Chairman can also be a member | In the first live run the chairman, Claude Sonnet 5.5, also wrote response A, which the peer ranking put first. The chairman sees letters, not names, but may still favour its own model's answer | Compare chairmen with `--chairman` on a few questions, then decide whether the default chairman should come from outside the members |
| CI results for milestone 2 unconfirmed | The milestone 2 run took 10.5 minutes and its secret scan passed, but the test job results have not been checked | Check on the Actions page |
| Cost estimate is a ceiling | The pre-run check assumes every model writes the longest answer allowed, so it can refuse runs that would have cost less | Revisit with measured data in milestone 5 |
| No interactive model picker | Profiles are built with `conclave profile add`; an interactive picker may come later | Not scheduled |

## How to keep this file current

- A change that adds or changes a capability ticks its task here, updates the README's [what works today](../README.md#what-works-today) table, and adds a line to the [changelog](../CHANGELOG.md), in the same commit.
- A new task goes under its milestone. Work that fits no milestone goes in "Known issues and follow-ups".
- When a milestone is done, update the summary at the top, the milestones table and its tag.
