# 0002: Public code, private research store

Date: 2026-10-07. Status: accepted.

## Context

Conclave is an open-source project, and its whole purpose is to accumulate a person's research. Those two facts pull against each other: the code should be public, and the research should not be.

## Decision

The code lives in a public repository under the MIT licence. The research store lives outside that repository, at a path set in the config, and is recommended to be its own private Git repository.

API keys are read from the environment or a `.env` file, which is never committed.

## Consequences

- The store path is configuration, never a fixed folder inside the code tree.
- `.gitignore` ignores `.env`, `research/` and `conclave-research/` as a safety net, and a test fails if those rules are removed.
- CI runs a secret scan on every push.
- The store stays on the user's device and search needs no network. Two things leave the device and the README says so: recalled text is sent to model providers in each run's prompt, and the store reaches a Git remote only if the user pushes it.
- The project must work on other people's machines: no hard-coded paths, one install command, and Windows, macOS and Linux all covered by CI.
