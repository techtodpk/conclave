# 0005: Claim labels, a source overlap check, and an optional devil's advocate

Date: 2026-10-07. Status: accepted. Labels and the overlap check were built in milestone 5 ([0011](0011-web-search-and-claim-checking.md)); the devil's advocate pass is deferred.

## Context

Models can all agree and all be wrong, especially when they read the same web page or learned the same mistake. A confident summary built on that is worse than one model's hedged answer. Four models quoting one blog post is one opinion.

## Decision

Three safeguards:

1. **A label on every key claim** in the final page: verified, agreed but unchecked, single source, or disputed. On every full run.
2. **A source overlap check** in code. It compares the links each member cited; when they all lean on one page, the claim is marked single source however many members agree. On every full run, at no model cost.
3. **A devil's advocate pass.** One low-cost model argues against the consensus, and the chairman must answer its strongest point. Only in deep mode, because it adds a model call to the run.

The user's own notes for a topic are read on every run and take precedence over the council's earlier conclusions.

## Consequences

- Members must return their claims and the links behind them in a structured form, so the overlap check has something to compare.
- The final page states what was checked and what was not. Agreement is never presented as proof.
- None of this makes the output certain. It still needs the reader's judgement.
