# 0010. Kiki owns its event schema

- Status: Accepted
- Date: 2026-10-17
- Related: NFR-0.4, FR-0.13

## Context
The log, the terminal and the future UI all need to know what was heard, what tools ran, what was said and how long it took. Pipecat's RTVI protocol offers similar events but only over a client transport, and would tie our data shape to Pipecat.

## Options considered
- Pipecat RTVI events: free with WebRTC/WebSocket transports, not with the local mic, not ours.
- Our own `turn` and `state` events: one shape for log, terminal and UI.

## Decision
Own schema, defined in ARCHITECTURE.md. A `turn` event is exactly one log line. RTVI may carry our events later, but never defines them.

## Consequences
+ Transport-independent: same events for text, laptop mic and the M5.
- Adding fields is free. Renaming or removing fields needs an ADR.
