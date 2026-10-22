# Changelog

What actually shipped, newest first. Format: [Keep a Changelog](https://keepachangelog.com/). One entry per tagged step.

## [Unreleased]

### Added
- A native UI on the Tab5 (`device/kiki`, ADR 0033, proposed): LVGL with Inter text and the Speaking Orb's particles ported to the device, at ~40 fps (~36 fps speaking), fed by Kiki's events. Build with `device/kiki/build.ps1`.

### Fixed
- A command with no words (noise after "hey jarvis") left Kiki "thinking" until the next command; it now goes back to idle after 3 s (FR-0.13).
- The Tab5's speaker could keep its mic paused for good when a part chunk of audio was left over; it is now dropped after 200 ms (`device/stream`, `device/kiki`).

## [v0.14] - 2026-10-21

Tab5 on the fridge.

### Added
- An M5Stack Tab5 as Kiki's screen, mic and speaker, a thin client of the laptop over the home Wi-Fi (ADR 0027, ADR 0032). Its program is `device/stream`; `device/check` checks its screen, touch, mic and speaker.
- `python -m kiki.screen` streams the real UI page to the Tab5: a headless Chrome renders it at 720×1200 and the newest JPEG frame goes out each time the Tab5 has shown the last; touches come back as touch events (FR-0.31, ADR 0028).
- An on-screen keyboard in the page streamed to the Tab5 (FR-0.32).
- `KIKI_MIC=tab5`: Kiki listens through the Tab5's mic, 20 ms UDP packets from a task of its own (FR-0.29, ADR 0029).
- `KIKI_SPEAKER=tab5`: the chime and replies play on the Tab5, paced by the clock 0.15 s ahead (FR-0.30, ADR 0029). Its mic and speaker take turns (ADR 0030).
- A volume bar along the bottom of the Tab5's screen: applied to the samples under a ceiling that can't clip, with a compressor, saved on the Tab5, starting at 5% (ADR 0031).
- `KIKI_UI_HOST` opens the UI server to the home network; it then accepts requests addressed to an IP address as well as `localhost` (NFR-0.7 replaces NFR-0.6).

### Changed
- NFR-0.8 replaces NFR-0.2: audio stays in the home, between the Tab5 and the laptop at most. Only command text reaches the model, tested through the Tab5's mic path too.
- The `speak` test fixture moved to `tests/conftest.py`, shared by `test_voice.py` and `test_tab5.py`.

### Fixed (on the way, before release)
- The Tab5's mic lost a third of its audio: connection attempts blocked the loop that sent it, Wi-Fi power saving dropped packets, and the USB log waited for a reader. Now 500 of 500 packets every 10 s.
- Replies on the Tab5 were choppy (Kiki fell behind real time) and then garbled and loud (mic and speaker running at once on separate clocks).

## [v0.13] - 2026-10-21

Whole replies.

### Fixed
- A reply after a quiet spell could lose its first words ("Milk is added to your list" played as "your list"). Windows let the idle speaker output fall asleep; Kiki now writes silence to it between sounds (FR-0.28).
- The voice latency test (NFR-0.3) failed at about 2.2 s. The laptop was on battery, where Whisper and Piper run about 1.6 times slower; plugged in, the same code measured 1.7 s. The 0.4 s grace period from v0.8 is not part of the measured time.

### Changed
- Whisper runs on 8 CPU threads instead of faster-whisper's default 4 (`KIKI_WHISPER_THREADS`): about 0.15 s faster per command plugged in, 0.24 s on battery. Median end of speech to first audio is about 1.5 s plugged in.
- The latency test warms up the model client first, as `python -m kiki.voice` does, so its first command no longer pays the ~5 s start-up.

## [v0.12] - 2026-10-21

List model.

### Added
- Every item has a buying pattern, Frequent or Occasional, and a status, Needed or Not needed (FR-0.19, ADR 0026, terms in CONTEXT.md). Frequent items always stay on the list; Not needed ones show dimmed and labelled.
- A usual quantity per item: "add butter" brings a Not needed item back at its usual quantity, "get three tomatoes" sets this time only, "we usually get three tomatoes" changes the usual (FR-0.20, FR-0.22).
- "Make chicken frequent", "we don't buy beetroot any more" and "call yogurt Greek yogurt" (FR-0.23, FR-0.24).
- Clicking an item in the UI flips it between Needed and Not needed (`POST /item`, FR-0.27).

### Changed
- Remove, "got the" and "not this time" make an item Not needed instead of deleting it; clear makes every item Not needed (FR-0.21 and FR-0.26 replace FR-0.5 and FR-0.7). Nothing is ever deleted.
- "What's on my list?" reads the Needed items, then only how many Frequent items are off this time (FR-0.25 replaces FR-0.6).
- An existing `kiki.db` isn't migrated: its old table is kept as `items_before_v0_12` and Kiki starts with an empty list.

## [v0.11] - 2026-10-17

Follow-up window, again.

### Added
- After each spoken reply Kiki keeps listening for 5 seconds (`KIKI_FOLLOW_UP_SECS`), so another command needs no "hey jarvis". No chime; the orb listens, then goes back to idle if nobody speaks (FR-0.18, ADR 0025).
- Speech in the window that isn't a command (a movie, people talking) gets no reply and opens no new window: the guard v0.6 lacked. It is still logged, with nothing said.
- Each follow-up is a standalone command; Claude still sees no previous turns (ADR 0009).

## [v0.10] - 2026-10-17

Speaking Orb and a calmer layout.

### Changed
- The orb is the Speaking Orb from Ship Notes (MIT, vendored as `speaking-orb.js`, ADR 0024): a particle sphere that listens, thinks in ribbons, swells while Kiki speaks, and shows the reply as captions that fly out of it. A finished turn ends on a check mark. Its colors are Framer's exact tokens: white at rest and listening, violet thinking, magenta speaking, green done (FR-0.17). Idle is small and dim; "hey jarvis" makes it grow, brighten and ripple.
- Layout: one centered column (orb, state, last run, list in two columns), with the text box docked to the bottom of the window. The last run is one line of what was heard and what changed; all runs are in a History sheet from the top bar. The same layout works on a phone.
- The text box is a pill composer; example commands fill it before the first run. Quantities show only when more than one.
- docs/ui.md rewritten for the new layout; DESIGN.md's Kiki overrides map every element to a Framer component.

## [v0.9] - 2026-10-17

Framer look.

### Changed
- The UI keeps its v0.4 layout and behavior and takes its look from DESIGN.md, the Framer template plus a "Kiki overrides" section (FR-0.16): near-black canvas, charcoal panels, white pill Send button, Inter/system type with Framer's sizes and tracking, the orb in Framer's orange, coral and magenta.
- Dark only; the light theme is gone.
- Changed list rows get a blue ring instead of a yellow flash. Errors use one red token, `semantic-error`.
- The old DESIGN.md (what the UI shows and does) moved to docs/ui.md; DESIGN.md now holds only the visual system.

## [v0.8] - 2026-10-17

List commas.

### Fixed
- The comma pause in a spoken list ended the command: "Add milk, two apples and some rice" was heard as "Add milk." and the rest was lost (FR-0.14). When a pause sounds finished, Kiki now waits 0.4 s more; speech in that grace period keeps the same command (ADR 0023, restored on its own from v0.6 without the follow-up window). `KIKI_END_GRACE_SECS` sets it. A finished command now ends about 0.66 s after the last word instead of 0.26 s.

### Changed
- Real-model voice tests feed audio at real-time pace (`RealTimeMic`); fed all at once, Smart Turn judged the wrong audio and the comma problem stayed hidden. Voice-scenario failures now show what Whisper heard.

### Added
- End-to-end test: "Hey Jarvis. Add milk, two apples and some rice." reaches the agent as one command. It fails 2 of 3 runs with the grace period off and passes every run with it on.

## [v0.7] - 2026-10-17

Sounds and wake word, tuned by ear and from real use.

### Changed
- The listening chime is a soft "glass" tone instead of a bare beep: a sine with gentle 2nd and 3rd harmonics, a click-free attack and a 1.2 s ring-out, rendered at 48 kHz, rising from C6 to G6. Picked by ear from three styles (glass, marimba, bell). Its level is a peak of 0.45 (about -7 dBFS): 0.32 went unnoticed and 0.7 was too loud. `KIKI_CHIME_VOLUME` sets it.
- Wake threshold 0.4 instead of 0.5. A real "hey jarvis" scored 0.46 and only crossed 0.5 about 0.3 s later, so the chime came late. Background speech has scored at most 0.24 so far.

### Added
- The terminal logs every wake word with its score, and near-misses (0.1 up to the threshold) with their best score, to tune `KIKI_WAKE_THRESHOLD` from real use. The fading tail of a wake word that was heard isn't counted as a miss.

### Removed
- The chime when Kiki stops listening (FR-0.11 updated). The reply, or the silence, says it.

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
