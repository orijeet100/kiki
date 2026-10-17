# 0015. Use Pydantic AI for the agent

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.3, FR-0.8, FR-0.9, FR-0.10, NFR-0.5. Builds on 0005 (model choice) and 0008 (plain tools).

## Context
The first v0.1 agent was a hand-written tool loop on the `anthropic` SDK. The owner wants the model to be easy to swap later, and wants checks and guards that come prebuilt rather than hand-rolled.

## Options considered
- Keep the hand-written Anthropic loop: no framework, but tied to one provider, and validation, retries and loop limits are ours to maintain.
- Pydantic AI: model-agnostic `provider:model` strings, typed tool arguments validated by Pydantic, retries via `ModelRetry`, output validators, usage limits, and `FunctionModel` / `TestModel` for offline tests.

## Decision
Pydantic AI (`pydantic-ai-slim[anthropic]`). `KIKI_MODEL` holds a Pydantic AI model string, default `anthropic:claude-haiku-5-5`. `tools.py` stays plain (ADR 0008); `agent.py` wraps each tool for Pydantic AI. Guards used: typed arguments, `ModelRetry` on tool errors, an output validator for spoken style, `retries=2`, `UsageLimits(request_limit=6)`, and the unified `thinking="low"` setting.

## Consequences
+ Switching provider is an env change plus that provider's extra and key.
+ Offline tests drive the real agent with a scripted model.
- Pydantic AI re-renders instructions on every request inside a run, so the list snapshot must be taken once per turn (see ARCHITECTURE.md, request flow).
- Sync tools run in worker threads, so the SQLite connection allows cross-thread use.
- A fast-moving dependency (2.x). Pin and read release notes before upgrading.
