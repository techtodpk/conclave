# Conclave design

This is the working design for v1. It describes what will be built across the eight milestones; the [README](../README.md) says what works today.

## Goal

Conclave is a local tool that sends one question to several LLMs with web search, makes them critique each other, checks the key claims, and saves a one-page answer into a topic folder on your machine. Every later question on that topic reads that folder first.

| In v1 | Not in v1 |
| --- | --- |
| Command-line tool: `conclave ask "question" --topic name` | Web interface |
| Council members, chairman and checker chosen by the user and saved as profiles | Logging in to chat web apps with passwords |
| Web search, cross-critique and claim checking on every full run | Vector database or embeddings |
| Local research store in plain Markdown files with a search index | Reading the store from the ChatGPT app |
| MCP server so Claude and Cursor read and write the same store | Multiple users or cloud sync |
| Personal leaderboard built from the models' rankings of each other | Public benchmark ranking chart (milestone 8) |

## The six stages of a full run

1. **Recall.** Load the topic's summary, open disputes and the user's notes.
2. **Research.** Each member answers alone. It may search the web, up to 3 times through OpenRouter's search tool on the Exa engine, and cites the pages it used.
3. **Critique.** Each member reviews the others' answers with names hidden, and ranks them. The rankings are saved.
4. **Verify.** The checker picks up to 8 key claims, preferring disputed claims and claims resting on one source. Conclave fetches the pages cited for them and gives the checker the passages that bear on each. The checker's verdict counts only if the words it quotes are in the page, and each claim's label is worked out in code ([0011](decisions/0011-web-search-and-claim-checking.md)).
5. **Synthesize.** The chairman writes one page: the answer, what the members agreed on, what they disputed, and the sources. Every key claim carries a label.
6. **Save.** Store the run, then update the topic's summary, disputes and sources.

A full run with N members makes 2N + 3 model calls: N answers, N reviews, two checking calls, the chairman's page and the memory update. Quick mode skips stages 2 to 4 and asks the chairman alone, with the recalled store and no web search.

## Components

| Component | Job | Built with |
| --- | --- | --- |
| Model client | Call any model, several in parallel, with or without web search | Two back ends behind one interface: an API caller for OpenRouter, and a subprocess runner for vendor command-line tools |
| Council engine | Run the six stages and hold the prompts for each | Plain Python, one function per stage, prompts as text files |
| Research store | Read and write topic folders, search past research | Markdown files plus a SQLite FTS5 full-text index, rebuildable from the files |
| CLI | `ask`, `search`, `topics`, `show`, `models`, `leaderboard` | Typer |
| MCP server | Expose the store and the council to Claude and Cursor | The official MCP Python SDK over stdio |

The MCP server needs four tools: `search_research`, `get_topic`, `ask_council` and `add_note`.

## Research store layout

```
<store>/
  index.sqlite               full-text index, rebuilt from the files
  topics/
    <topic-slug>/
      memory.json            the record of claims and disputes
      summary.md             the active claims, written from memory.json
      disputes.md            disagreements, open or resolved, written from memory.json
      sources.md             every page cited, by run: who cited it, whether it was fetched, what it checked
      notes.md               your own notes; the council reads these first
      runs/
        <date>-<question-slug>/
          question.md
          recall.md          the earlier research the council was given
          answers/<model>.md
          critiques/<model>.md
          rankings.json      each model's ranking of the others
          sources.json       every page the members cited, and whether it could be fetched
          verification.md    each key claim checked: verdict, quote, label (and verification.json)
          final.md           the one-page answer, ending with what changed in memory
          memory_patch.json  memory changes proposed, applied and refused
          meta.json          profile, models, tokens, cost, timings
```

Two rules keep the store trustworthy:

- **Runs are never edited.** Each run folder is a permanent record of what every model said.
- **The council changes only the topic's memory.** `memory.json`, and the `summary.md` and `disputes.md` written from it, are updated after each full run, with one Git commit per run when the store is a Git repository. `notes.md` belongs to the user and is only appended to.

## Safeguards

| Risk | Safeguard |
| --- | --- |
| Cost per question | Budget caps per run and per month, quick mode by default, low-cost models for critique |
| Models agree and are all wrong | A label on every key claim, a source overlap check, and an optional devil's advocate pass |
| The summary drifts over many runs | The summary is a list of claims updated by patch, never rewritten whole |
| Thin web search | Each member searches for itself; every run logs distinct sources and the share of claims verified |
| Private research in a public repository | The store lives outside the code repository; `.gitignore` and a CI secret scan back that up |
| Subscription terms change | Every command-line route can be switched back to the API in the config |

The reasoning behind each of these is recorded in [decisions](decisions/).
