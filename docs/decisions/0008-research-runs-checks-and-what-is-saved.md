# 0008: Research runs: checks before sending, and what is saved

Date: 2026-10-07. Status: accepted.

## Context

Milestone 2 makes the first real model calls. That raised four practical questions the earlier decisions did not settle: how the budget caps are enforced when a run has not happened yet, where the cost figure comes from, what to keep when calls fail, and how a user adds a council without hand-editing TOML.

## Decision

**Check before sending.** Before any model is called, Conclave fetches the live model list and:

- stops if a model id is not in the list, suggesting the closest ids from the same vendor;
- works out the worst-case cost of the run, assuming every model reads the whole prompt and writes the longest answer allowed, and stops if that is above the cap for the run's mode.

If the model list cannot be fetched, the run goes ahead with a note that the cost could not be estimated. Being unable to look up prices should not stop someone from working.

**Cost comes from OpenRouter.** Each call asks OpenRouter to report its cost, and that figure is recorded. If it is missing, the cost is computed from the token counts and the listed prices and marked "estimated".

**The monthly cap uses the store.** The month's spending is the sum of the recorded cost of every run started this calendar month. There is no separate ledger to drift out of step with the runs.

**Partial success is kept; total failure is not.** If some members fail, the other answers are saved and the failures are recorded in `meta.json`. If no model answers, nothing is saved: the store holds research, not failed attempts.

**Runs use the final layout from the start.** A run is saved under `topics/<topic>/runs/<date-time>-<question>/` even though topic summaries arrive in milestone 4, so no migration is needed later.

**Profiles are added by command.** `conclave profile add` validates the ids against the live list and appends the profile to the config file, leaving the rest of the file and its comments untouched. An interactive picker can be layered on top later.

**Answers share one structure.** Every member is asked for an answer, a numbered list of the key claims it depends on with a confidence for each, and what it is unsure of. The Critique and Verify stages will work from those claim lists.

## Consequences

- A run costs one extra, unauthenticated request for the model list.
- The worst-case estimate is deliberately pessimistic, so a cap set very low can refuse runs that would have cost less. The message says which settings to change.
- Token counts in the estimate use a rough four-characters-per-token rule. Real counts come back from the API and are what is recorded.
- Spending through a different tool on the same OpenRouter key is not counted. Prepaid credit remains the hard ceiling.
- Because member answers are requested without web search until milestone 5, the prompt tells models not to invent sources and to date anything that may have changed.
