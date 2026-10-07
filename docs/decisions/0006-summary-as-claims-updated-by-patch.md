# 0006: The summary is a list of claims, updated by patch, automatically

Date: 2026-10-07. Status: accepted.

## Context

Each topic's `summary.md` is the memory every later run reads. If a model rewrites it whole after each run, detail is lost over time, and one wrong claim that slips in is repeated to every future council as if it were established.

## Decision

- **Claims, not free prose.** Each line in the summary is one claim with its label, its date, and a link to the run it came from.
- **Patch, not rewrite.** The chairman proposes lines to add, change or retire, and code applies them. A line is retired only with a stated reason.
- **An entry rule.** Only verified or agreed claims enter the summary. Disputed ones go to `disputes.md`; single-source ones enter flagged.
- **Applied automatically**, with one Git commit per run when the store is a Git repository. A review flag asks for approval before saving, for topics where accuracy matters most.

## Consequences

- Every answer ends with "what changed in memory": the lines added, changed or retired in that run.
- Any run's effect on the memory can be seen as a diff and reverted.
- A rebuild command, planned after milestone 4, regenerates a summary from all saved runs and shows how it differs from the current one, as a drift check.
- Run folders are never edited, so the summary can always be rebuilt from them.
