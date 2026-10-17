# 0018. One model request per command: the `update_list` output function

- Status: Accepted
- Date: 2026-10-17
- Related: NFR-0.3, FR-0.1 to FR-0.7. Builds on 0008 (plain tools), 0015 (Pydantic AI).

## Context
With one tool per operation, every change took two model requests: one to call the tool, one to phrase the reply. Measured agent time for a change was 1.3–2.0 s, which pushed end of speech → first audio to about 3 s (NFR-0.3 asks for about 2 s). "What's on my list?" also cost two requests because the model called `read_list` even though the list was already in its instructions.

## Options considered
- Keep per-operation tools: simplest mental model, two requests per change.
- Turn thinking off: measured no faster.
- A single Pydantic AI output function, `update_list(reply, add, remove, set_quantities, clear)`, plus plain-text output for questions: one request per command.

## Decision
The agent's outputs are `[ToolOutput(update_list), str]`. The model makes every change from the sentence in one call and writes the reply in the same call, from the list snapshot it already has. Questions are answered in plain text from the snapshot; `read_list` is no longer offered to the model. `update_list` calls the unchanged plain tools in a fixed order: clear, remove, add, set quantities.

## Consequences
+ Agent time ~0.75 s for questions and ~0.9–1.2 s for changes; voice median total ~1.5 s.
+ All steps are idempotent, so a retry after `ModelRetry` re-applies safely.
+ Parallel tool calls on one SQLite connection can no longer happen.
- The reply is written before the tools run. It relies on the snapshot, which is exact for a single-turn command; if a step reports an error, `ModelRetry` gives the model a chance to correct the reply.
