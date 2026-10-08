# Changelog

Each milestone on the [roadmap](README.md#roadmap) is tagged in Git when it is complete.

## Milestone 2: council core (2026-10-07)

Version 0.2.0.

- `conclave ask "question"` asks the council and saves every answer to the research store. Quick mode asks the chairman; `--full` asks every member at the same time. `--topic` files the run under a topic, `--profile` picks a council, and `--members` asks a one-off set of models.
- Each run is saved as plain files: `question.md`, one answer file per model, and `meta.json` with tokens, cost and timings.
- Answers follow one structure: the answer, the key claims it depends on with a confidence for each, and what the model is unsure of.
- `conclave models` lists available models with live prices, with `--search`, `--vendor`, `--sort` and `--limit`.
- `conclave profile add` adds a council profile to the config after checking every model id against the live list.
- Budget caps are enforced. The worst-case cost of a run is worked out before anything is sent, and the run is refused if it is above the cap. Full runs pause when the month's recorded spending reaches the monthly cap.
- The API key is read from the environment or a `.env` file, and is never printed or stored.
- One member failing never loses the others' answers. Rate limits and provider errors are retried twice.
- New setting `run.max_answer_tokens` (default 1500).
- Tests run against a simulated OpenRouter: no key, no cost, no network.

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
