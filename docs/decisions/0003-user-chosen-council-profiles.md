# 0003: The council is chosen by the user and saved as profiles

Date: 2026-10-07. Status: accepted.

## Context

A fixed line-up of models goes stale within months, and different users have different budgets and different subscriptions. The value of a council comes from members with different blind spots, which matters more than any single model's strength.

## Decision

A **profile** names the members, the chairman and the checker, and each model's route. Profiles live in the config; three ship as a starting point (`lean`, `balanced`, `full`). A run can override the profile's members with a flag.

`conclave models` will list available models with live prices and let the user build a profile. It warns when two members come from the same vendor.

Two aids guide the choice:

- **A personal leaderboard**, in v1. In the Critique stage every member ranks the others' answers. Those rankings are saved with each run, so the tool can show which model wins on the user's own questions and topics.
- **A public ranking chart**, in milestone 8. One row per model, one column per published benchmark, with price beside it.

## Consequences

- Rankings from the Critique stage are stored with every run (`rankings.json`), not discarded.
- The public chart uses only published APIs and datasets, keeps each source in its own column with its date and link, and never blends sources into one score. Planned sources: Artificial Analysis (free API, attribution required), LMArena (dataset under CC BY 4.0), LiveBench and DeepSWE (licences still to check; DeepSWE measures coding only).
- Each source names models differently, so the repository needs a hand-maintained mapping file.
- Default model ids are OpenRouter ids as listed in October 2026 and must be kept current.

## Sources

- [Artificial Analysis API documentation](https://artificialanalysis.ai/documentation)
- [LMArena leaderboard dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)
- [LiveBench](https://github.com/livebench/livebench)
- [DeepSWE](https://deepswe.datacurve.ai/)
