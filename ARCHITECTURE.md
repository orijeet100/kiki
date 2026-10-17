# Architecture

How Kiki works right now. Update this file in the same commit as any code change that alters it. For *why* each choice was made, see [docs/adr/](docs/adr/README.md).

## Overview

```
v0.1 (terminal)
  keyboard ──> cli.py ──> agent.py (Pydantic AI) ──> model API ──> tools.py ──> db.py ──> kiki.db
                  ^            │
                  └── reply ───┤
                               └──> events.py ──> logs/turns.jsonl

v0.2 (voice: voice.py, a Pipecat pipeline around the same agent)
  mic ──> WakeGate ──> VADProcessor ──> EndOfTurnDetector ──> WhisperSTTService ──> Brain ──> PiperTTSService ──> speaker
          (openWakeWord, (Silero)       (faster-whisper,      (run_turn) (Piper, local)
           local)                        local)

v0.4 (UI: ui.py, started by voice.py or on its own)
  events.publish ──> ui.py (http.server, Server-Sent Events) ──> browser on 127.0.0.1:8765
  browser text box ──> POST /command ──> run_turn (same path as voice)
```

| Layer | Choice | ADR |
|---|---|---|
| Orchestration | Pipecat | [0002](docs/adr/0002-use-pipecat-for-voice-orchestration.md) |
| Wake word | openWakeWord, built-in "hey jarvis", runs before STT | [0003](docs/adr/0003-gate-audio-with-local-wake-word.md) |
| Audio in/out (v0.2) | Pipecat `LocalAudioTransport`, Python owns mic and speaker | [0011](docs/adr/0011-python-owns-the-mic-in-v0.md) |
| STT | faster-whisper `base.en` with a grocery-vocabulary prompt, int8 on CPU | [0004](docs/adr/0004-run-stt-and-tts-locally.md), [0019](docs/adr/0019-whisper-base-with-vocabulary-prompt.md) |
| Agent framework | Pydantic AI: tool loop, argument validation, retries, output guard, usage limit | [0015](docs/adr/0015-use-pydantic-ai-for-the-agent.md) |
| Brain | Any Pydantic AI model string, default `anthropic:claude-haiku-5-5` | [0005](docs/adr/0005-use-claude-haiku-by-default.md), [0015](docs/adr/0015-use-pydantic-ai-for-the-agent.md) |
| TTS | Piper, voice `en_US-lessac-medium` (Kokoro if Piper sounds too robotic) | [0004](docs/adr/0004-run-stt-and-tts-locally.md) |
| State | SQLite, one file | [0006](docs/adr/0006-store-state-in-sqlite.md) |
| Host | The laptop, permanently | [0007](docs/adr/0007-laptop-is-the-permanent-host.md) |

## Code layout

```
src/kiki/
  db.py       SQLite connection and schema
  tools.py    the tool functions (plain Python, no voice or model knowledge)
  agent.py    one command in, one turn out: the Pydantic AI agent, its instructions, tools and guards
  events.py   appends turn events to the log
  cli.py      terminal loop (v0.1)
  ui.py       local UI server (v0.4): page, live events, typed commands
  ui.html     the whole UI: one file, no build step, no dependencies
  latency.py  median latency per stage from the turn log (v0.3)
  voice.py    voice loop (v0.2): WakeGate, Brain, the processor chain, the mic/speaker runner
tests/
  test_tools.py       tools.py against a temp SQLite file
  test_events.py      turn log format
  test_agent.py       agent loop against Pydantic AI's FunctionModel / TestModel
  test_scenarios.py   ROADMAP scenarios against the real Claude API (marked `scenario`)
  test_latency.py     latency report
  test_ui.py          UI server over real HTTP with a scripted model
  test_voice.py       wake gate with a fake detector; real models on Piper-synthesized speech (marked `voice`)
```

`src/` layout is uv's default for a package (`uv init --lib`).

## Request flow (one turn)

1. A command arrives as text (typed in v0.1, transcribed in v0.2).
2. `run_turn` snapshots the list once, then calls `agent.run_sync` with only the command. The model sees the static instructions, the snapshot and the command. No previous turns ([ADR 0009](docs/adr/0009-single-turn-commands.md)), with one exception: a spoken follow-up also gets the previous command as one line of context, marked as already done ([ADR 0022](docs/adr/0022-follow-up-window-after-each-reply.md)).
3. **One model request** ([ADR 0018](docs/adr/0018-one-model-request-per-command.md)). The model either answers in plain text (questions, "Sorry, I didn't catch that.") or calls the output function `update_list(reply, add, remove, set_quantities, clear)` once, with every change from the sentence and the spoken reply. `update_list` runs the plain tools in a fixed order (clear, remove, add, set quantities), records each in `Deps.tool_calls`, and returns `reply` as the output. No second request is needed to phrase the reply.
4. `run_turn` returns a `turn` event. `events.py` appends it to the log. The caller prints or speaks `said`.

**Why the snapshot is taken once:** Pydantic AI re-renders instructions on every model request inside a run, retries included. A live list read after a retry would show "bread x2", and the model would bump "add another bread" again (found by scenario 3 in v0.1).

**Why retries are safe:** every step of `update_list` is idempotent (adding a present item is a no-op, removing a missing item is a no-op, clearing and setting a quantity are absolute), so re-applying a call after a retry changes nothing twice.

### Guards (all Pydantic AI built-ins)

| Guard | What happens |
|---|---|
| Argument validation | `update_list` arguments are typed (`Item.quantity >= 1`). Invalid arguments never reach `tools.py`; the model gets a retry prompt. |
| Tool errors | A tool result with an `error` key is raised as `ModelRetry`, so the model sees the message and can correct itself. The call is still logged. |
| Output guard | `spoken_style` output validator rejects markdown, bullets, underscores and digits with a retry, for plain-text replies and for the `reply` of `update_list` (FR-0.10). Empty replies are retried by Pydantic AI itself. |
| Retries | `retries=2`. They also bound the number of model requests per turn. |
| Request timeout | `timeout=10` seconds: a stalled request becomes "I can't reach the internet right now." instead of hanging for the client's default ten minutes. |
| Model settings | `thinking="low"` (unified setting, maps to each provider's effort), `max_tokens=4096`. |

### Failure replies

| Failure | `said` | `error` |
|---|---|---|
| Retries exhausted, no speakable reply | "Sorry, I didn't catch that." | `UnexpectedModelBehavior: ...` |
| No internet or timeout (`ModelAPIError`) | "I can't reach the internet right now." | `connection error` |
| API error (`ModelHTTPError`) | "Something went wrong, please try again." | `API error <status>` |
| Any other run error | "Something went wrong, please try again." | exception name and message |

Tools that ran before a failure stay in `tool_calls`, so the log still shows them (for example, a `clear_list` that ran before the connection dropped).

**SQLite and threads:** Pydantic AI runs sync functions in worker threads and voice turns run in a thread too, so `db.connect` uses `check_same_thread=False`. Only one `update_list` runs per turn and turns are sequential, so the connection is never used concurrently.

**Model client:** built per turn with `infer_model`. `warm_up()` builds one at startup (voice, terminal, UI) to pay the one-time cost of about three seconds before the first command. A client must not be cached across turns: its connections belong to the event loop of the thread that first used it, and a turn on another thread (the UI and voice both use worker threads) then stalls until the request timeout. That cost 11 s per turn until v0.4.

**One turn at a time:** `run_turn` holds a process-wide lock, so a typed command and a spoken one never use the SQLite connection at the same time.

## Voice loop (v0.2)

`python -m kiki.voice` runs `Pipeline([mic, *processors(conn), speaker])` on Pipecat's `LocalAudioTransport` at 16 kHz.

| Processor | Job |
|---|---|
| `WakeGate` | Scores every 80 ms of mic audio with openWakeWord's bundled "hey jarvis" model, **always and locally**. While closed it drops the audio, so VAD and Whisper never see it (NFR-0.1). On the wake word it plays the listening chime and opens. After each spoken reply it also opens, silently, for `KIKI_FOLLOW_UP_SECS` (5 s), starting 0.3 s after playback so the tail of Kiki's own voice isn't heard; an unused window closes silently (FR-0.16). It closes, with the done chime, when `EndOfTurnDetector` says the command is finished (one command per wake word) or after `KIKI_LISTEN_TIMEOUT_SECS` with no speech. If the wake word comes while Kiki is speaking, it broadcasts an `InterruptionFrame` first, which stops the speech (FR-0.12). |
| `VADProcessor` | Silero VAD. Reports speech starts and every pause of `KIKI_PAUSE_SECS` (0.2 s). |
| `EndOfTurnDetector` | At each pause, asks Smart Turn v3.2 (bundled ONNX model, ~60 ms on CPU) whether the sentence sounds finished from its intonation. Unfinished: hides the pause, so Whisper keeps buffering the same command and the gate stays open. Finished and still silent `KIKI_END_GRACE_SECS` (0.4 s) later, or after `KIKI_MAX_PAUSE_SECS` (3 s) of silence: sends one stop to Whisper and `UserStoppedSpeakingFrame` up to the gate ([ADR 0021](docs/adr/0021-smart-turn-ends-the-command.md), FR-0.14). Speech within the grace period, like the next item after a list comma, keeps the same command ([ADR 0023](docs/adr/0023-grace-period-after-a-finished-sounding-pause.md)). |
| `WhisperSTTService` | Transcribes each speech segment locally with `base.en` and a short grocery-vocabulary `initial_prompt` ([ADR 0019](docs/adr/0019-whisper-base-with-vocabulary-prompt.md)). |
| `Brain` | Runs `run_turn(transcript, source="voice")` in a thread, passing the previous command when this one started within the follow-up window, pushes the reply as `TTSSpeakFrame`, and logs the turn when the first reply audio plays. |
| `PiperTTSService` | Speaks the reply locally. |

Chimes are 16 kHz sine tones generated in code: rising (660 → 990 Hz) when listening starts, falling when it stops (FR-0.11).

**Voice latency fields** in the `turn` event: `stt` = end of speech → transcript; `llm` = agent run; `tts` = reply ready → first audio; `total` = end of speech → first audio (NFR-0.3). "End of speech" is when `EndOfTurnDetector` decides the command is finished: about 0.66 s after the last word for a finished-sounding sentence (0.2 s pause, ~60 ms check, 0.4 s grace). `python -m kiki.latency [n]` prints the medians over the last n voice turns from the log.

Measured on this laptop (v0.3, synthesized speech, CPU only):

| Stage | Median |
|---|---|
| `stt` (Whisper `base.en`) | ~0.55 s |
| `llm` (one request: questions ~0.75 s, changes ~0.9–1.2 s) | ~0.9 s |
| `tts` (Piper first audio) | ~0.08 s |
| `total` | **~1.5 s** (v0.2 was ~3.0 s) |

**Always on:** the pipeline worker runs with `idle_timeout_secs=None`; Pipecat's default would shut it down after a quiet spell.

Only the transcript text crosses the network (to the model API). Audio, the wake model, VAD, Whisper and Piper all run on the laptop (NFR-0.2).

## UI (v0.4)

`python -m kiki.voice` serves the UI at http://127.0.0.1:8765 next to the voice loop; `python -m kiki.ui` serves it alone (text box only, no microphone). Standard library only ([ADR 0020](docs/adr/0020-ui-over-server-sent-events.md)).

| Route | What |
|---|---|
| `GET /` | `ui.html` |
| `GET /events` | Server-Sent Events: one `snapshot`, then every `state`, `turn` and `list` event; a keep-alive comment every 15 s |
| `POST /command` | `{"text": "..."}` → 202, then the turn runs in a background thread and its events arrive on `/events` |

The page shows an orb whose look follows `state`, the list (rows that changed flash briefly), and run cards (heard, what changed as chips, what was said, total latency; per-stage latency and raw tool calls under Details). Dark and light follow the system setting; animations stop under reduced motion. Every value from the log is inserted as text, never as HTML.

**Safety, since any web page in the browser could try to reach a local server:**
- Binds to 127.0.0.1 only (NFR-0.6).
- Rejects requests whose `Host` isn't `127.0.0.1` or `localhost` (blocks DNS rebinding).
- `POST /command` requires `Content-Type: application/json`, which other sites can't send without a CORS preflight that the server never answers.
- Commands are 1 to 200 characters.

**One Kiki at a time (FR-0.15):** the voice loop and `kiki.ui` bind the UI port first. On Windows the server doesn't set `SO_REUSEADDR` (which there would let a second process share the port), so a second copy fails with "Kiki is already running" before loading any models. Two copies used to both answer every command.

## Matching names

`normalize()` in `tools.py` maps singular and plural to one key with suffix rules: lowercase, collapse spaces, drop a trailing `s` (not `ss`, `us`, `is`), then `ie` to `y` and drop the `e` of `oe`, `che`, `she`, `xe`, `sse`. The key isn't always a real word ("cookie" becomes "cooky"); it only has to match both forms. Irregular plurals ("loaves") aren't handled.

## Data model

One table, `items`:

| Column | Type | Notes |
|---|---|---|
| `id` | integer primary key | |
| `name` | text | As the user said it ("eggs") |
| `normalized_name` | text, unique | Lowercase, singular ("egg"). Used for matching |
| `quantity` | integer, default 1 | |
| `created_at` | text (ISO 8601) | |
| `updated_at` | text (ISO 8601) | |

## Tools

All tools are plain functions taking and returning JSON-compatible values ([ADR 0008](docs/adr/0008-tools-are-plain-functions.md)). The model never calls them directly; it calls `update_list`, which calls them.

| Tool | Input | Output | Notes |
|---|---|---|---|
| `add_items` | `items: [{name, quantity?}]` | `{added: [...], already_present: [...]}` | Never changes the quantity of an existing item (FR-0.2) |
| `set_quantity` | `name, quantity` | `{name, quantity}` or `{not_found: name}` | For explicit changes like "add another milk" or "make it three" (FR-0.3). The model computes the new number from the list snapshot |
| `remove_items` | `names: [string]` | `{removed: [...], not_found: [...]}` | Deletes the whole item regardless of quantity (FR-0.5) |
| `read_list` | none | `{items: [{name, quantity}]}` | Builds the snapshot; not offered to the model, since the snapshot already answers questions |
| `clear_list` | none | `{removed: [{name, quantity}]}` | No confirmation. The removed items land in the turn log ([ADR 0012](docs/adr/0012-clear-list-without-confirmation.md)) |

## Events

Kiki defines its own event shapes ([ADR 0010](docs/adr/0010-own-event-schema.md)). The log, the terminal and the future UI all use them.

**`turn`**, one per command, appended as one line to `logs/turns.jsonl`:

```json
{
  "type": "turn",
  "id": "t_20261017T180211_3f2a",
  "ts": "2026-10-17T18:02:11Z",
  "source": "text",
  "heard": "add bread and two milks",
  "previous_command": null,
  "tool_calls": [
    {"name": "add_items",
     "args": {"items": [{"name": "bread", "quantity": 1}, {"name": "milk", "quantity": 2}]},
     "result": {"added": [{"name": "bread", "quantity": 1}, {"name": "milk", "quantity": 2}],
                "already_present": []}}
  ],
  "said": "Added bread and two milks.",
  "model": "anthropic:claude-haiku-5-5",
  "latency_ms": {"stt": null, "llm": 1650, "tts": null, "total": 1650},
  "error": null
}
```

- `previous_command` is the command just before, when this one was a spoken follow-up (FR-0.16); otherwise null.
- `source` is `text` or `voice`. `stt` and `tts` latencies are `null` in v0.1. `llm` is the whole agent run (model requests plus tool time), so in v0.1 it equals `total`.
- `error` is null, or a short string when the turn failed (for example, no internet).

**`state`**, live only and not logged:

```json
{"type": "state", "value": "idle | listening | thinking | speaking | error"}
```

| Value | Published by | When |
|---|---|---|
| `listening` | `WakeGate` | wake word heard, or a reply finished (follow-up window) |
| `thinking` | `WakeGate`, `ui.send_command` | end of a command, before the agent answers |
| `idle` | `WakeGate`, `Brain`, `ui.send_command` | nothing said after the wake word; reply finished |
| `speaking` | `Brain` | first reply audio plays (`BotStartedSpeakingFrame`) |
| `error` | `Brain`, `ui.send_command` | the turn had an `error` (shown until the next state) |

**`list`**, live only: the whole list after every turn, `{"type": "list", "items": [{"name", "quantity"}]}`.

**`snapshot`**, sent once to each UI connection: `{"type": "snapshot", "state", "items", "turns"}` with the last 50 turns from the log.

`events.publish` fans events out to in-process subscribers (one queue per open page). `events.record_turn` is what every caller runs after a turn: append to the log, publish the turn, publish the list.

Adding a field is fine. Renaming or removing one needs an ADR.

## Instructions

The source of truth is `INSTRUCTIONS` in `agent.py`, plus a dynamic line "Current list at the start of this request: ...". In short: speak in one or two short sentences with numbers as words; make every change in one `update_list` call; answer questions in plain text; fix obvious speech-to-text slips ("got the X" is often heard as "cut", "dot" or "gut"); never change an existing item unless the quantity change is explicit; remove means delete completely; read every item when asked; after clearing say only the count; when unsure reply exactly "Sorry, I didn't catch that." and call no tools.

## Configuration

Environment variables only. A local `.env` is fine (never committed) and is loaded with `uv run --env-file .env ...`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none, required for the default model | Claude API key. Another provider needs its own key (e.g. `OPENAI_API_KEY`) |
| `KIKI_MODEL` | `anthropic:claude-haiku-5-5` | Pydantic AI model string, `provider:model`. Swap with e.g. `openai:<model>`; `test` runs Pydantic AI's offline TestModel |
| `KIKI_DB` | `kiki.db` | SQLite file path |
| `KIKI_LOG` | `logs/turns.jsonl` | Turn log path |
| `KIKI_WAKE_THRESHOLD` | `0.5` | openWakeWord score (0–1) that counts as "hey jarvis". Raise if it wakes by itself, lower if it misses you |
| `KIKI_LISTEN_TIMEOUT_SECS` | `6` | How long the gate stays open after the wake word if nobody speaks |
| `KIKI_PAUSE_SECS` | `0.2` | A pause this long makes Smart Turn check whether the sentence sounds finished |
| `KIKI_END_GRACE_SECS` | `0.4` | After a pause sounds finished, how long to wait for more words before closing |
| `KIKI_MAX_PAUSE_SECS` | `3` | Silence that ends a command even if it sounded unfinished |
| `KIKI_FOLLOW_UP_SECS` | `5` | How long Kiki listens after each reply without the wake word |
| `KIKI_WHISPER_MODEL` | `base.en` | faster-whisper model name. `small.en` is more robust but adds about 1.1 s |
| `KIKI_PIPER_VOICE` | `en_US-lessac-medium` | Piper voice; downloaded on first run to `~/.cache/pipecat/piper` |
| `KIKI_UI_PORT` | `8765` | UI port (always on 127.0.0.1) |

## Dependencies

Approved. Anything else needs the owner's yes and an ADR.

| Dependency | Why | Since |
|---|---|---|
| `pydantic-ai-slim[anthropic]` | Agent framework and Anthropic provider ([ADR 0015](docs/adr/0015-use-pydantic-ai-for-the-agent.md)). Another provider is a new extra, e.g. `[openai]` | v0.1 |
| `sqlite3` (stdlib) | State | v0.1 |
| `pytest` (dev) | Tests | v0.1 |
| `ruff` (via `uvx`, not installed) | Lint and format | v0.1 |
| `pipecat-ai[local,silero,whisper,piper]` | Voice pipeline; pulls in PyAudio, faster-whisper and `piper-tts` | v0.2 |
| `openwakeword` | Wake word (0.4.x: ONNX models bundled, works on Windows) | v0.2 |

`piper-tts` is GPL-3.0. Fine for a personal assistant; if Kiki is ever distributed, switch to `PiperHttpTTSService` or Kokoro.

The UI adds no dependencies: `http.server`, Server-Sent Events and one HTML file.

## Testing

- `test_tools.py`, `test_events.py`, `test_agent.py`: deterministic, no network. Always run. `test_agent.py` scripts the model with Pydantic AI's `FunctionModel`, so it checks what the model is sent, retries and guards without an API call.
- `test_voice.py`: the gate tests use a fake detector and are instant. Real-model tests put `RealTimeMic` first, which releases audio at real-time pace: Smart Turn and VAD keep wall-clock time, and audio pushed all at once was judged wrong. Waits are streamed silence, never `SleepFrame`, because a real mic keeps sending silence and the 3 s fallback counts it. Tests marked `voice` run the real wake word, Silero, Whisper and Piper on speech synthesized by Piper ([ADR 0017](docs/adr/0017-test-voice-with-synthesized-speech.md)); `test_scenario_by_voice` (also marked `scenario`) speaks the seven v0.2 scenarios to the real agent. First run downloads the Whisper and Piper models.
- `test_latency.py`: the log report. `test_voice.py::test_nfr_0_3_*` (marked `voice` and `scenario`) speaks twenty commands through the full chain to the real agent and requires a median `total` of 2 s or less.
- `test_ui.py`: real HTTP against a server on a random port with a scripted model: the page, the live event sequence for a typed command (`thinking`, `turn`, `list`, `idle`), past runs in the snapshot, localhost binding, and the Host, content-type and length checks.
- `test_scenarios.py`: sends each ROADMAP scenario to the real model and asserts on tool calls and final list state, not on exact wording. A full run is 11 short Haiku turns, well under a cent. Needs `ANTHROPIC_API_KEY`; skipped automatically without it, or deselect with `-m "not scenario"`.
