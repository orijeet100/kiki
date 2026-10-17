# 0005. Use Claude Haiku by default

- Status: Accepted
- Date: 2026-10-17
- Related: NFR-0.3, NFR-0.5

## Context
Parsing "add bread and two milks" into tool calls is easy. Latency and cost matter more than peak capability.

## Options considered
- `claude-sonnet-5-5`: more capable, slower and pricier.
- `claude-haiku-5-5`: fast and cheap.

## Decision
`claude-haiku-5-5` by default, set by `KIKI_MODEL`. Switch to Sonnet only if the scenario tests fail on Haiku.

## Consequences
+ Lower latency and cost.
- No internet means no assistant (accepted for v0).
