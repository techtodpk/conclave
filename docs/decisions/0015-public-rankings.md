# 0015: Public rankings beside the council's own

Date: 2026-10-15. Status: accepted. Builds on [0003](0003-user-chosen-council-profiles.md).

## Context

Decision 0003 planned a public ranking chart: one row per model, one column per published benchmark, price beside it, next to the personal leaderboard that comes from members ranking each other. Four sources were named. Checked in October 2026:

- **Artificial Analysis** has a free API for its model data, including its Intelligence Index and prices, with a free key, 1,000 requests a day, a request to cache, and the condition that "attribution is required for all use of our free API".
- **LMArena** publishes its leaderboards as a Hugging Face dataset under CC BY 4.0: model name, company, rating, rank, vote count and publish date, with a `latest` split. The overall text leaderboard published on 13 October 2026 has 415 models. It needs no key.
- **LiveBench** publishes its code under Apache 2.0, but no licence for its results, and no ready results file; the leaderboard would have to be rebuilt from raw answers.
- **DeepSWE** states no licence, and its dataset asks for contact details before download.

The sources name models their own way. OpenRouter's `anthropic/claude-sonnet-5.5` is `claude-sonnet-5.5-xhigh` on LMArena, which also lists `-high`, `-max` and dated variants of many models.

## Decision

**Sources.** LMArena's overall text leaderboard and Artificial Analysis' Intelligence Index. LiveBench and DeepSWE wait until their results are published under clear terms.

**Fetching.** At most once a day per source, cached in the research store under `.cache/rankings/`. `--refresh` or the app's Refresh button fetches again. A source that cannot be read keeps its last cached copy and says so with its date; with no copy, it is left out with the reason. Artificial Analysis is used only when the user adds a key, `ARTIFICIAL_ANALYSIS_API_KEY`, in the environment or the `.env` file beside the config, as with the OpenRouter key; the app can save it there.

**Matching.** A model matches a source's entry with the same company and the same name, compared loosely (case, dots and dashes), allowing an ending for the reasoning level or build date: `-low`, `-medium`, `-high`, `-xhigh`, `-max`, `-thinking`, `-reasoning` or an eight-digit date. When several match, the best-rated one is used and its name is shown, so `gpt-6.1-sol-pro-max` is never taken for `gpt-6.1-sol`. `model_names.toml` overrides the guess for a model that is missed or matched wrongly.

**The table.** One row for each model in the user's councils, each model on their own leaderboard, and the ten best of each source among models OpenRouter offers. Columns: each source's figure and rank, the council's own score (0 = always ranked best by the other members, 1 = always worst, with the number of reviews) and OpenRouter's prices. `conclave rank` prints it; the app's Rankings page shows it with a bar per figure.

**Attribution.** Every view names each source, what its number measures, its credit line, the date of the ranking and a link to the full leaderboard.

## Consequences

- No source is needed for any other feature; the rankings never change who sits on a council.
- The public figures measure different things from the council's score: LMArena counts which of two anonymous answers people preferred, Artificial Analysis averages its own benchmark runs, and the council's score counts how the other members ranked an answer on the user's own questions. The views say so rather than combining them.
- Loose matching can miss a model or pick a variant the user did not mean; the variant's name is always shown, and `model_names.toml` corrects it.
- Fetching LMArena reads a few hundred rows from Hugging Face's dataset service once a day.

## Sources

- [Artificial Analysis API reference](https://artificialanalysis.ai/api-reference)
- [LMArena leaderboard dataset](https://huggingface.co/datasets/lmarena-ai/leaderboard-dataset)
- [LiveBench repository](https://github.com/livebench/LiveBench)
- [DeepSWE](https://deepswe.datacurve.ai/)
