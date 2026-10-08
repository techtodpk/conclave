# 0012: The MCP server

Date: 2026-10-08. Status: accepted.

## Context

The research store is most useful where the user already works: in Claude Desktop, Cursor and other assistants that speak the Model Context Protocol. An assistant connected to the store can check what the council already concluded before answering, and start a new council run when the store has no answer. That also lets an assistant spend the user's money and write into a store whose notes outrank the council, so both need limits.

The official MCP Python SDK reached version 2 in July 2026, with an `MCPServer` class that builds tool schemas from type hints and runs over stdio.

## Decision

`conclave mcp` runs an MCP server over stdio, built on the official SDK (`mcp>=2.3,<3`). It is an optional extra, `pip install -e ".[mcp]"`, so the command line does not depend on it.

Six tools:

| Tool | Reads or writes |
| --- | --- |
| `list_topics`, `search_research`, `get_topic`, `get_run` | Read only, and marked read-only for the client |
| `ask_council` | Runs a question and saves it, as `conclave ask` does |
| `add_note` | Appends a note to a topic |

Rules:

- **Quick by default.** `ask_council` runs a quick run unless the assistant passes `full=true`. The tool description and the server's instructions say what each costs, so the assistant can tell the user.
- **The same checks as the command line.** Planning a run, the per-run and monthly caps, the key check and the credit check live in one module that both the command line and the server call. An assistant can do nothing the user could not do from the terminal, and nothing beyond the caps.
- **Assistants' notes are marked.** A note added through MCP ends with "(added by <client> via MCP)", using the name the client gives for itself, so the user can tell it from their own.
- **No new access.** The server reads only the research store named in the config. `get_run` refuses run names that would leave the topic's folder. The API key is never returned by any tool.
- Nothing is printed to stdout, which carries the protocol.

## Consequences

- One install step and one config entry per client; the setup guide gives both for Claude Desktop and Cursor on Windows and macOS.
- A full run takes one to two minutes inside a single tool call. Clients that time out tool calls sooner will show an error even though the run finishes and is saved.
- Deleting or editing the memory is not offered to assistants. Changing a claim still happens only through a full run, under the rules in decision 0010.
- Every MCP-started run is an ordinary run in the store, with the same files and the same Git commits.

## Sources

- [MCP Python SDK](https://pypi.org/project/mcp/)
- [Connect to local MCP servers](https://modelcontextprotocol.io/docs/develop/connect-local-servers)
