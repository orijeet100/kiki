# 0008. Tools are plain functions

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.1 to FR-0.7

## Context
The same tools must work from the terminal, the voice pipeline and tests, and may later move behind a separate process or MCP server.

## Decision
`tools.py` holds plain Python functions with JSON-compatible input and output. They know nothing about voice, Pipecat or Claude. `agent.py` maps Claude tool calls onto them.

## Consequences
+ Tools are testable without the API, and reusable unchanged in v0.2.
- `agent.py` keeps the tool schemas for Claude in sync with the functions.
