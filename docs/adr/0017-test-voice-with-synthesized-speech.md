# 0017. Test the voice loop with speech synthesized by Piper

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.11, NFR-0.1, NFR-0.2, v0.2 definition of done

## Context
Voice behavior needs end-to-end checks that run without a person talking into a microphone.

## Options considered
- Manual testing at the mic only: real, but slow and unrepeatable.
- Recorded WAV fixtures: real voices, but binary files in the repo and a fixed set of phrases.
- Synthesize speech with Piper (already a dependency) and feed it as mic frames through the app's own processor chain.

## Decision
Synthesize with Piper, resample to 16 kHz, feed as 20 ms `InputAudioRawFrame`s through `voice.processors(...)` with Pipecat's `run_test`. A feasibility check scored Piper's "Hey Jarvis" at 0.999 on openWakeWord and Whisper transcribed the command exactly. These tests are marked `voice`.

## Consequences
+ Wake word, VAD, Whisper, agent and Piper are all exercised on every run, with no human and no fixtures.
- Synthesized speech is cleaner than a real kitchen. Tuning wake sensitivity and pauses still needs a person at the mic (v0.3).
