# Changelog

What actually shipped, newest first. Format: [Keep a Changelog](https://keepachangelog.com/). One entry per tagged step.

## [Unreleased]

## [v0.3] - 2026-10-17

Tuned. Median end of speech to first audio went from about 3.0 s to about 1.5 s (NFR-0.3).

### Changed
- One model request per command: the agent calls a single `update_list(reply, add, remove, set_quantities, clear)` output function or answers in plain text (ADR 0018). `read_list` is no longer offered to the model.
- Whisper `base.en` with a grocery-vocabulary prompt instead of `small.en`: 0.5 s instead of 1.6 s, same accuracy on the test commands (ADR 0019).
- The model client is built once at startup (`load_model`), so the first command is no longer about 3 s slower.
- Requests time out after 10 s instead of the client's default 10 minutes.
- The agent treats "cut/dot/gut the X" as Whisper's mishearing of "got the X" (scenario 12).

### Added
- `python -m kiki.latency [n]`: median latency per stage over the last n voice turns.
- Tests: NFR-0.3 latency test (20 spoken commands through the full chain, median must be 2 s or less), one-request and ordering tests for `update_list`, scenario 12.

### Fixed
- Parallel tool calls from one model response could hit the shared SQLite connection at the same time and crash. Gone by design: one `update_list` call per turn.

### Known issues
- The v0.3 definition of done also asks for a week of daily use with rare false wakes and cut-offs. That needs a person at the mic; `KIKI_WAKE_THRESHOLD`, `KIKI_VAD_STOP_SECS` and `KIKI_WHISPER_MODEL` are the knobs.

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
