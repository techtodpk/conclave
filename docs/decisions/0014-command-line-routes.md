# 0014: Command-line routes on the user's own plan

Date: 2026-10-11. Status: accepted. Builds on [0001](0001-api-by-default-cli-adapters-optional.md) and [0011](0011-web-search-and-claim-checking.md).

## Context

Decision 0001 promised optional adapters for vendors' own command-line tools, so a council seat can run on a subscription the user already pays for. Before building them, each tool was run on Windows in October 2026 with a one-line research question:

- **Claude Code 2.1.296** (`claude -p --output-format json`) answered with cited Markdown links after one web search. With its default setup, that one question read about 225,000 tokens, worth $0.43 at API prices, because Claude Code sends its whole coding-assistant prompt, the user's MCP servers and settings with every call. With its system prompt replaced and MCP servers, slash commands and session files turned off, the same question read about 17,000 tokens, worth $0.026. Since 7 October 2026 Claude's Max and Team plans include a monthly API credit that covers `claude -p`; on Pro it draws on the plan's usage limits.
- **Codex CLI 0.160.1** (`codex exec --json`, with `--search`) answered with a cited link after one search and one page opened. It reports each search and the pages it found as JSON events. It signs in with a ChatGPT plan, and when the plan's Codex allowance runs out it says so and gives the reset time.
- **Gemini CLI** no longer accepts Google sign-in for individuals; it says to move to the Antigravity suite. **Antigravity CLI 1.3.2** (`agy -p --output-format json`) answered with a cited link, but only when told not to open pages: in headless mode it cannot ask permission to read a URL, so it stops with an empty answer. Its citations are Google redirect links.

## Decision

A seat with `route = "cli"` is answered by the vendor's tool: `anthropic/...` models by Claude Code, `openai/...` by Codex CLI, `google/...` by Antigravity CLI. Other vendors have no command-line route.

**How each call runs.**

- One run of the tool per call, non-interactive, in a new empty temporary folder that is deleted afterwards, so the tool reads no project files.
- Web search is the only tool, and only in the Research stage of a full run. Claude Code gets `--tools WebSearch`; Codex runs in its read-only sandbox, with `--search` only when searching; Antigravity is told in the prompt to search only and not open pages, and runs with `--sandbox`. In every other stage the tools are told not to use any tool, and Claude Code gets none.
- Claude Code gets Conclave's prompt in place of its own system prompt, with MCP servers, slash commands and session files off. Codex runs with `--ephemeral` and without asking for approval.
- The prompt goes on standard input for Claude Code and Codex, so Windows command-line quoting cannot break it. Antigravity takes it as an argument; a prompt longer than a Windows command line allows is refused with a plain message.
- A call that takes longer than 5 minutes is stopped.
- The model name is worked out from the id (`claude-sonnet-5.5` becomes `claude-sonnet-5-5`; `gemini-3.8-flash` becomes `gemini-3.8-flash-low` at the run's reasoning level). `cli_model` in the config overrides the guess.

**Sources.** The links an answer cites as Markdown become its sources, as Exa citations do on the API route, so claim checking works the same way. Codex's search results add excerpts for the pages it cites. Searches are counted where the tool reports them (Claude Code, Codex); Antigravity does not report them.

**Cost.** A call on the user's plan costs nothing against Conclave's caps: it is recorded at $0 with the source "plan", and left out of the pre-run estimate. The tokens it used are still recorded, and for Claude Code so is what the call would have cost at API prices. A run in which every seat is on a plan needs no OpenRouter key.

**Errors.** A missing tool is caught before anything is sent, with how to install it, how to sign in, and that `route = "api"` switches back. A tool's own error, such as a usage limit or a sign-in prompt, is passed on in its own words, prefixed with the tool's name. As on the API route, one seat failing never loses the others' answers.

**Setup.** `conclave tools` shows which tools are installed and their versions. The app's council editor has a "Run on your own plan" box for each Claude, GPT and Gemini seat, and keeps a hand-set `cli_model` when a council is edited.

## Consequences

- Personal use only, as decision 0001 says: each vendor's terms decide what a plan covers, and they have changed several times in 2026. Every seat switches back to the API with a one-word config change.
- These tools cannot be given a length limit, so the prompts' requested lengths are the only limit on a command-line seat's answer.
- A command-line seat is slower than the API: about 10 to 25 seconds for a short question, more with searches.
- Tests never start a real tool: an automatic test fixture refuses to, because a stray run would spend the developer's plan.
- Gemini CLI is replaced by Antigravity CLI for Google models. Decision 0001's mention of Gemini CLI is out of date.

## Sources

- [Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Codex non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [Antigravity CLI headless mode](https://antigravity.google/docs/cli/headless/)
- [Gemini CLI quotas and pricing](https://geminicli.com/docs/resources/quota-and-pricing/)
