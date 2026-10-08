# Changelog

Each milestone on the [roadmap](README.md#roadmap) is tagged in Git when it is complete. Work in progress and pending tasks are tracked in [project status](docs/STATUS.md).

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
