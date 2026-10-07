# Changelog

Each milestone on the [roadmap](README.md#roadmap) is tagged in Git when it is complete.

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
