# Changelog

What actually shipped, newest first. Format: [Keep a Changelog](https://keepachangelog.com/). One entry per tagged step.

## [Unreleased]

### Added
- The terminal logs each wake word with its score, and near-misses (0.1 up to the threshold) with their best score, to tune `KIKI_WAKE_THRESHOLD` from real use. The fading tail of a heard wake word isn't counted as a miss.

### Changed
- The listening chime is louder (-3 dBFS instead of -10) and rings longer (1.2 s instead of 0.7): at the old level it went unnoticed.

### Removed
- The chime when Kiki stops listening. Only the listening chime plays now (FR-0.11 updated).

### Changed
- Softer chimes: the bare 16 kHz beeps are replaced by "glass" tones (sine plus gentle harmonics, click-free attack, natural ring-out, 48 kHz), picked by ear from three styles. Rising fifth when listening starts, falling pair when it stops.

### Reverted
- v0.6 (the 5-second follow-up window and the end-of-command grace period) is rolled back to v0.5 behavior. With a movie playing, the follow-up window took the dialogue as commands, and each answer opened a new window, so Kiki kept listening and answering. Kiki again listens only after "hey jarvis". The v0.6 work stays in git (tag `v0.6`) and the mic watchdog is parked on the `v0-listening-state-fix` branch.

## [v0.5] - 2026-10-17

Natural pauses, from the first days of real use.

### Changed
- A pause mid-sentence no longer ends the command (FR-0.14). VAD now reports every 0.2 s pause, and a new `EndOfTurnDetector` asks Pipecat's bundled Smart Turn model whether the sentence sounds finished. Unfinished pauses are hidden from Whisper; the command ends when it sounds finished or after 3 s of silence (ADR 0021). A finished sentence is now recognized about 0.26 s after the last word instead of 0.8 s.
- Knobs: `KIKI_PAUSE_SECS` (0.2) and `KIKI_MAX_PAUSE_SECS` (3) replace `KIKI_VAD_STOP_SECS`.

### Fixed
- Two copies of Kiki could run at once on Windows and both answer every command (seen in the log as duplicate turns). A second copy now exits with "Kiki is already running" (FR-0.15).

### Added
- Tests: end-of-turn detector with a scripted analyzer; end to end, "Hey Jarvis. Can you add one … (1.2 s pause) … garlic and one onion?" is heard as one command; second instance refused.

## [v0] - 2026-10-17

v0 is done: one household grocery list, edited and read back by voice on the laptop, with a local UI to watch it work. Steps v0.1 to v0.4 below. Still for the owner: a week of daily use to tune wake sensitivity and pauses (v0.3), and the real UI design in DESIGN.md (v0.4 shipped a first cut).

## [v0.4] - 2026-10-17

A local UI at http://127.0.0.1:8765: an orb that follows Kiki's state, the list, and every run.

### Added
- `ui.py` + `ui.html`: standard-library HTTP server with Server-Sent Events and one HTML page, no dependencies (ADR 0020). Started by `python -m kiki.voice`, or alone with `python -m kiki.ui` (text box, no microphone).
- Live events: `state` (listening, thinking, speaking, idle, error) from the wake gate, the voice Brain and typed commands; `list` after every turn; `snapshot` with the last 50 runs on page load.
- Safety: 127.0.0.1 only, Host check against DNS rebinding, JSON-only commands (no cross-site posts), 200-character limit.
- First-cut design recorded in DESIGN.md, with the open questions.
- Tests: UI server over real HTTP, event bus, gate state events, sentence-count guard, a real-API test that turns on new threads don't stall.

### Fixed
- Turns run on a new thread (UI, sometimes voice) stalled about 11 s: the v0.3 model client cache tied connections to the first thread's event loop. The client is now built per turn (~40 ms) after a start-up warm-up.
- Replies longer than two sentences are sent back for a retry (FR-0.10).
- Typed and spoken commands can't run at the same moment (process-wide turn lock).

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
