# 0009: How members review each other and how the chairman sums up

Date: 2026-10-08. Status: accepted.

## Context

Milestone 3 adds the two stages that turn several separate answers into one: Critique and Synthesis. Each needed choices about what each model sees, how rankings are read, how claims are labelled before any claim checking exists, and how the budget applies to a run that now has three stages.

## Decision

**Hidden names.** Successful answers are given letters, A, B, C, in the order of the profile's members. Reviewers and the chairman see only the letters. The model behind each letter appears only in the saved files and at the end of the final page.

**Reviewers never see their own answer.** Each member reviews every other answer and ranks them. Ranking one's own answer adds a known bias for little benefit, so it is left out.

**Rankings are read strictly.** A ranking is taken from the last "Ranking" heading in a review, and only if every expected letter appears exactly once. Anything else is recorded as unreadable and left out of the averages. A guessed ranking would quietly distort the leaderboard planned for milestone 4; a missing one is visible.

**Standings are average positions.** Each answer's score is its average place across the readable rankings, lower being better. Answers no reviewer could rank are listed last as "not ranked".

**The chairman writes, code frames.** The chairman writes the answer, the labelled key claims, the disagreements and the open questions. The title, the warning that nothing was checked against live sources, and the "how this answer was made" table are added by code, so they are always present and always accurate.

**Three labels until claim checking exists.** Every key claim is labelled "agreed but unchecked", "single model" or "disputed". The "verified" label is held back until milestone 5 can check claims against sources, so no claim is presented as verified when it was not.

**The budget covers the whole run.** Before anything is sent, the worst case for all three stages must fit the cap. Before Critique and before Synthesis, the check runs again with what has really been spent and the real size of that stage's prompt. A stage that could break the cap is not started, and everything up to it is kept.

**Failures keep what exists.** If only one member answers, there is nothing to compare, so Critique and Synthesis are skipped. If some reviews fail, the chairman works from the rest. If the chairman fails, the answers and reviews are kept.

**Review and page lengths.** A review may use up to 1,000 tokens, or the answer limit if lower. The chairman's page may use the answer limit plus 1,000 tokens.

## Consequences

- A full run with N members makes 2N + 1 calls: N answers, N reviews and one page. The design's 2N + 2 included a checker call, which arrives with milestone 5.
- With the default `balanced` profile, the worst case for a full run rose from about $0.04 to about $0.12 at October 2026 prices, still well under the $0.75 cap.
- Models can recognise each other's writing style, so the letters reduce bias rather than remove it.
- `--chairman` lets the same question be run with different chairmen, which is how the chairman comparison in decision 0003 will be done.
