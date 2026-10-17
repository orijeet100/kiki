# 0011. Python owns the mic in v0 (LocalAudioTransport)

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.11, NFR-0.1, NFR-0.2

## Context
v0.2 needs mic and speaker on the laptop. The UI arrives only in v0.4.

## Options considered
- Browser owns the mic via WebRTC (SmallWebRTCTransport): RTVI events for a UI, but the page must stay open and it adds aiortc and FastAPI.
- Python owns the mic via `LocalAudioTransport`: only adds PyAudio, works headless, same approach as the reference repo.

## Decision
`LocalAudioTransport` for v0. The M5 transport (WebSocket vs WebRTC) is decided by a new ADR when the hardware arrives.

## Consequences
+ No browser or web server needed for voice.
- The v0.4 UI needs its own small event channel (local WebSocket) fed by our events (ADR 0010).
