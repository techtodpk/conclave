# 0001: API by default, subscription command-line tools as optional adapters

Date: 2026-10-07. Status: accepted.

## Context

People who would use Conclave often already pay for several AI subscriptions, so paying again per question is a real objection. A subscription to a chat app generally cannot be used from other software: logging in to the web apps with stored passwords breaks often, risks the account, and is against the providers' terms.

Some vendors do ship official command-line tools that run on a personal plan. Anthropic's support pages say Pro and Max subscribers can use `claude -p` for personal scripts, drawing on the plan's usage limits, and that third-party apps authenticating with a subscription are not permitted. In 2026 Anthropic announced that this usage would move to separate billing, then paused the change. Gemini CLI publishes daily request quotas for Google account sign-in. For Codex CLI, OpenAI's documentation recommends an API key for automation.

Rough estimates made at design time, to be replaced by measurements: about $0.40 for a full run of four members on the API alone, and about $0.10 when two members run through command-line tools.

## Decision

The default route for every model is a pay-per-use API through one OpenRouter key, so that anyone who clones the project can run it with a single credential.

Vendor command-line tools are supported as optional adapters, chosen per model with `route = "cli"` in the config. They are documented as personal use only, and the user is responsible for checking their own plan's terms.

## Consequences

- The model client needs two back ends behind one interface: an API caller and a subprocess runner.
- Every adapter must be switchable back to the API by a config change, because plan rules can change.
- Calls made through an adapter cost nothing against the budget caps, but are still counted and logged, since they draw on the user's plan limits.
- Cost per run is logged from milestone 2 so the estimates above can be replaced with real numbers.

## Sources

- [Use the Claude Agent SDK with your Claude plan](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
- [Gemini CLI: quotas and pricing](https://geminicli.com/docs/resources/quota-and-pricing/)
- [OpenAI Codex: non-interactive mode](https://learn.chatgpt.com/docs/non-interactive-mode)
- [OpenRouter FAQ](https://openrouter.ai/docs/faq)
