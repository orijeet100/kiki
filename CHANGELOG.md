# Changelog

What actually shipped, newest first. Format: [Keep a Changelog](https://keepachangelog.com/). One entry per tagged step.

## [Unreleased]

## [v0.1] - 2026-10-17

Terminal grocery list. Type a command; the agent updates the list, replies in one spoken-style sentence, and logs the turn.

### Added
- Project docs: README, ROADMAP (v0 requirements), ARCHITECTURE, DESIGN placeholder, AGENTS rules, ADRs 0001–0015.
- SQLite list with singular/plural matching, and five plain tools: `add_items`, `set_quantity`, `remove_items`, `read_list`, `clear_list`.
- Single-turn agent on Pydantic AI (ADR 0015), default model `anthropic:claude-haiku-5-5`, swappable via `KIKI_MODEL`. Guards: typed tool arguments, tool-error retries, spoken-style output validator, request limit.
- JSONL turn log (`logs/turns.jsonl`) and the terminal loop (`python -m kiki.cli`).
- Tests: 27 offline (tools, log, agent with Pydantic AI's FunctionModel) and all 11 ROADMAP scenarios passing against the real API.

### Known issues
- First command after start takes about 5 s, later ones about 1.5–2 s. The model sometimes calls `read_list` even though the list is in its instructions. Both are for v0.3 latency tuning.
- Irregular plurals ("loaves") don't match their singular.
