# 0011: Web search and claim checking

Date: 2026-10-08. Status: accepted. Builds on [0005](0005-guarding-against-shared-blind-spots.md) and [0007](0007-each-member-searches-for-itself.md).

## Context

Until milestone 5 every answer came from the models' training data. The first live topic showed why that is not enough: a reviewer said PEP 779 does not exist, and the chairman then called a correct citation unreliable. Agreement and confident review cannot settle a factual point; only a source can.

OpenRouter offers web search in three ways, as of October 2026: a `web` plugin that runs one search before the model answers, an `openrouter:web_search` server tool that lets the model decide when to search, and each vendor's own native search. It offers several search engines; Exa costs $0.007 per search for up to 10 results and returns an excerpt of each page with the citation.

## Decision

**Search.** In a full run each member searches for itself through the `openrouter:web_search` server tool, on the Exa engine, at most `search.max_searches` times per answer (default 3), with at most 5 results per search and 10 per answer. The Critique, Verify, Synthesis and memory stages never search. Quick runs do not search. `--no-search` or `search.enabled = false` turns it off.

- One engine for every model keeps the price per search fixed and known before the run, and gives every citation an excerpt that checking can fall back on.
- Letting the model decide, within a cap, means it searches for what it is unsure of rather than once by rote.

**Checking.** After Critique, the profile's checker makes two calls:

1. It picks up to `run.claims_checked` key claims (default 8) from the answers and reviews, preferring disputed claims, claims resting on one source, and claims a reader would act on. It refers to sources by number from a list Conclave gives it, so it cannot invent a link.
2. Conclave fetches the pages cited for those claims, on the user's machine, and gives the checker the part of each page that bears on each claim. A page that cannot be fetched (an error, a paywall, a PDF, a page that needs JavaScript) is replaced by the search excerpt, and the verdict says so. The checker answers supported, contradicted or not found for each claim, quoting the deciding words.

**Code decides the outcome, not the model.**

- A verdict counts only if its quote is in the passage, word for word apart from case, spacing and punctuation. Otherwise the claim is "not found".
- Each checked claim's label is worked out in code: contradicted by a source, or disputed among members and not settled by a source, is disputed; supported is verified; otherwise two or more members from two or more websites is agreed but unchecked, all of them leaning on one website is single source (decision 0005's overlap check), and one member is single model.
- The chairman is given these labels and told to use them. A claim enters memory as verified only if it matches a claim the checker verified in that run.

**Records.** Each run saves `sources.json`, `verification.md` and `verification.json`. Each topic keeps `sources.md`, one section per run, with every page cited, whether it was fetched, and what it was used to check. `meta.json` records searches, distinct sources, pages fetched, and the share of checked claims verified (decision 0007's two numbers).

**Deferred.** The devil's advocate pass (`--deep`, decision 0005) moves to follow-ups, to keep this milestone to search and checking.

## Consequences

- A full run makes 2N + 3 model calls for N members: research, critique, two checking calls, synthesis and the memory update.
- The worst-case cost of a `balanced` full run rose to about $0.59, and of a `full` run to about $0.75, so the default full-run cap rose from $0.75 to $1.00. Existing config files keep their own caps.
- Search fees are included in the cost OpenRouter reports for each call, as the first live runs confirmed, so Conclave's totals include them.
- Search queries go to OpenRouter and its search provider; cited pages are fetched directly from the user's machine. Neither sees the research store.
- A page that is out of date or wrong can still verify a claim. "Verified" means a cited page states it, not that it is true; `verification.md` shows the quote so the reader can judge.
- Word-for-word quote matching will sometimes reject a fair verdict that paraphrased the page. That errs toward "not found", which is the safe direction.

## Addendum, 10 October 2026: at least one search

Letting the model decide when to search let a confident model skip it: in two full runs Claude Sonnet answered from training data alone, so a third of the council's claims had no page to check against. A full run now requires each member to search at least once before answering. If an answer comes back with no search and no cited page while search was working, Conclave asks that member once more, with a note that it has not searched; the second answer replaces the first, and both calls are paid for. If the second call fails, the first answer stands. The model still chooses what to search for and how often, within `search.max_searches`. The extra call is not in the pre-run cost estimate; the cap is checked again before each stage.

## Sources

- [OpenRouter web search](https://openrouter.ai/docs/web-search)
- [OpenRouter web search server tool](https://openrouter.ai/docs/guides/features/server-tools/web-search)
