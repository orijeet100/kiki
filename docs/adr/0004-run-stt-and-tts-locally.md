# 0004. Run STT and TTS locally (faster-whisper, Piper)

- Status: Accepted; STT model superseded by 0019
- Date: 2026-10-17
- Related: NFR-0.2, NFR-0.3

## Context
Audio must never leave the laptop. Speech is English only, in a fairly quiet kitchen. Latency target is about 2 seconds to first audio.

## Options considered
- Cloud STT/TTS: best quality, but audio leaves the house.
- faster-whisper `small` for STT: local, good enough for plain English.
- Piper vs Kokoro for TTS: Piper is fastest on a laptop CPU; Kokoro sounds more natural.

## Decision
faster-whisper `small` and Piper. Try Kokoro if Piper sounds too robotic.

## Consequences
+ Audio stays local, no per-use cost.
- Mixed-language or unusual item names would need a bigger model and a vocabulary prompt.
