# 0004: Budget caps per run and per month

Date: 2026-10-07. Status: accepted.

## Context

A full run makes 2N + 2 model calls for N members, and a long question or a large recalled context can make one run far more expensive than usual. Users need to know the tool cannot run away with their credit.

## Decision

Three caps, set in the config, in US dollars:

| Cap | Default | When it is reached |
| --- | --- | --- |
| Full run | 1.00 (0.75 before milestone 5) | The run stops before the next stage and saves what it has |
| Quick run | 0.10 (0.05 before milestone 4) | Same |
| Month | 15.00 | New full runs are refused until the cap is raised; quick runs still work |

The full-run default is about twice the design-time estimate for a full run on the API alone, so normal runs pass and a runaway one is stopped.

In milestone 4 the quick-run default rose from 0.05 to 0.10. Every call now reserves room for the model's hidden reasoning, and the worst case for a quick run with an Opus chairman (the `full` profile) came to about $0.08.

## Consequences

- Before a run, the tool estimates its cost from the profile's current prices.
- After each stage, it adds up actual spend from the usage figures the API returns.
- Prepaid OpenRouter credit remains the hard ceiling whatever the config says.
- The defaults come from a rough estimate and are to be reset from measured costs after milestone 2.

In milestone 5 the full-run default rose from 0.75 to 1.00, because web search and claim checking raised the worst case of a `full` profile run to about $0.75 ([0011](0011-web-search-and-claim-checking.md)).
