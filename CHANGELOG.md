# Changelog

What actually shipped, newest first. Format: [Keep a Changelog](https://keepachangelog.com/). One entry per tagged step.

## [Unreleased]

## [v0.2] - 2026-10-17

Voice on the laptop. Say "hey jarvis", hear a chime, say a command, hear the reply.

### Added
- `python -m kiki.voice`: Pipecat pipeline on the laptop mic and speaker: `WakeGate` (openWakeWord "hey jarvis") → Silero VAD → Whisper `small.en` → the v0.1 agent → Piper.
- Wake gate drops all audio until the wake word (NFR-0.1), lets one utterance through, closes on end of speech or a 6 s timeout, with rising/falling chimes (FR-0.11). The wake word while Kiki speaks interrupts it (FR-0.12). ADR 0016.
- Voice turns are logged with `source: "voice"` and stt/llm/tts/total latencies.
- Tuning knobs: `KIKI_WAKE_THRESHOLD`, `KIKI_LISTEN_TIMEOUT_SECS`, `KIKI_VAD_STOP_SECS`, `KIKI_WHISPER_MODEL`, `KIKI_PIPER_VOICE`.
- Tests: 5 instant gate tests; end-to-end tests that feed Piper-synthesized speech through the real wake word, VAD, Whisper and Piper (ADR 0017), including the seven v0.2 scenarios against the real agent. All pass.

### Known issues
- Not yet tuned with a person at the mic: wake sensitivity and the end-of-speech pause use defaults (v0.3).

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
