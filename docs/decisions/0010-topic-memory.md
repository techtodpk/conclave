# 0010: How a topic's memory is stored, recalled and updated

Date: 2026-10-08. Status: accepted.

## Context

Milestone 4 makes each question start from what earlier runs on the same topic concluded. Decision 0006 set the principles: the summary is a list of claims, updated by patch, automatically. Building it raised further questions: where the record lives, what the council is shown, which model writes the patch, what code checks, and what happens on Git.

## Decision

**memory.json is the record; the Markdown files are views.** Claims and disputes are kept in `memory.json`, and `summary.md` and `disputes.md` are written from it after every change. Parsing hand-edited Markdown back into claims would be fragile, and a broken parse could silently drop memory. The Markdown files say they are rewritten, and point the user to notes instead.

**Notes belong to the user.** `notes.md` is only ever appended to, by `conclave note`. Notes are recalled first, and the prompts say they take precedence over the council's conclusions.

**Recall goes to members and the chairman.** Before every question, quick or full, the topic's notes, active claims and open disputes are added to the research prompt and the chairman's prompt, with ids (C1, D1) so answers can say which earlier finding they confirm or correct. Reviewers are not given it; they judge the answers in front of them. Recall is cut at about 12,000 characters so it never crowds out the question.

**Only full runs change the memory.** A quick run has no critique, so nothing it says has been agreed by anyone.

**The chairman proposes; code decides.** After the one-page answer, the chairman is asked for a JSON patch: claims to add, change or retire, and disputes to open or resolve. Code applies it under fixed rules:

- a claim is added only with the label "agreed but unchecked" or "verified";
- "single model" points are not stored, and contested points become disputes, not claims;
- a change or retirement needs a reason and an existing active claim;
- near-duplicates of an active claim are not added;
- nothing is deleted: retired claims and resolved disputes stay visible with their reason;
- ids are never reused.

Everything proposed, applied and refused is saved in the run's `memory_patch.json`, and the changes are listed at the end of `final.md`.

**Failures leave the memory alone.** An unreadable patch, a failed call, a declined review, or a run stopped by its cap all leave `memory.json` unchanged, and say so.

**--review and --fresh.** `--review` shows the changes and asks before saving. `--fresh` neither reads nor writes the memory, for a clean comparison.

**Git, when present.** If the store is a Git repository, each run and each note is committed. A failed commit is reported but never loses the run.

**The search index is disposable.** `index.sqlite` is rebuilt from the files whenever any of them changes, using SQLite's FTS5 where available and a plain text match otherwise.

**The leaderboard scales places.** A place in a ranking of n answers scores (place − 1) / (n − 1), from 0 (best) to 1 (worst), so councils of different sizes can be compared.

## Consequences

- A full run makes one more call, the memory update. With the default `balanced` profile the worst case rose to about $0.14 at October 2026 prices, or about $0.18 on a topic with a long memory. After room for hidden reasoning was added to every call (see the changelog), these became about $0.28 and $0.31.
- Excluding "single model" points keeps the memory conservative: a correct point made by only one member is kept in that run's files but not recalled. Claim checking in milestone 5 can promote such points once a source supports them.
- `sources.md` arrives with web search in milestone 5, when there are sources to record.
- `conclave rebuild <topic>`, which would regenerate a summary from all runs as a drift check, is deferred until topics have enough runs to drift. The run folders keep everything it would need.
