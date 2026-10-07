# 0007: Each member searches the web for itself

Date: 2026-10-07. Status: accepted.

## Context

A research answer is only as good as the pages the models read. There are two ways to give a council web access:

| Approach | Strength | Weakness |
| --- | --- | --- |
| Each member runs its own search | Members find different pages, so their answers stay independent | A search charge per member, and depth depends on the search provider |
| One shared research pack for all members | Cheaper, deeper, and every claim traces to a page the tool holds | All members read the same sources, which is the shared blind spot decision 0005 guards against |

OpenRouter's built-in web search can be turned on for any model and by default returns up to five results per call, at a listed price of $4 per thousand results.

## Decision

Start with each member searching for itself through OpenRouter's built-in search. Keep search behind one function in the model client so the approach can be changed later.

Decide on upgrades from evidence. Every run logs two numbers: the count of distinct sources across members, and the share of key claims that passed verification.

## Consequences

- Different sources per member is what makes the source overlap check meaningful.
- The Verify stage fetches cited pages itself, so claim checking does not depend on which search route the members used.
- If the logged numbers stay low, the first upgrade to try is adding a search-native model as a member.

## Sources

- [OpenRouter web search](https://openrouter.ai/docs/features/web-search)
