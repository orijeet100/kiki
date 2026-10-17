# 0002. Use Pipecat for voice orchestration

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.11, FR-0.12, NFR-0.3

## Context
A voice loop needs streaming audio, voice activity detection, end-of-turn detection, interruptions and pluggable STT/LLM/TTS. Building these by hand is slow and error-prone.

## Options considered
- Hand-built loop on PyAudio: full control, lots of fiddly code.
- Pipecat (open source, Python): all of the above built in, local transports, used by the reference repo.

## Decision
Pipecat for the voice pipeline from v0.2. The agent and tools stay independent of it.

## Consequences
+ Turn-taking, VAD and interruptions come for free.
- We follow Pipecat's version changes. Pin the version in `pyproject.toml`.
