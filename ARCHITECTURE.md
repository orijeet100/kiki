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
  list click       ──> POST /item    ──> add_items / remove_items (no model, v0.12)
```

| Layer | Choice | ADR |
|---|---|---|
| Orchestration | Pipecat | [0002](docs/adr/0002-use-pipecat-for-voice-orchestration.md) |
| Wake word | openWakeWord, built-in "hey jarvis", runs before STT | [0003](docs/adr/0003-gate-audio-with-local-wake-word.md) |
| Audio in/out (v0.2) | Pipecat `LocalAudioTransport`, Python owns mic and speaker | [0011](docs/adr/0011-python-owns-the-mic-in-v0.md) |
| STT | faster-whisper `base.en` with a grocery-vocabulary prompt, int8 on CPU, 8 threads | [0004](docs/adr/0004-run-stt-and-tts-locally.md), [0019](docs/adr/0019-whisper-base-with-vocabulary-prompt.md) |
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
  ui.html     the whole UI: one file, no build step
  speaking-orb.js  the orb: vendored Speaking Orb web component, MIT (ADR 0024)
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
2. `run_turn` snapshots the list once, then calls `agent.run_sync` with only the command. The model sees the static instructions, the snapshot and the command. No previous turns ([ADR 0009](docs/adr/0009-single-turn-commands.md)).
3. **One model request** ([ADR 0018](docs/adr/0018-one-model-request-per-command.md)). The model either answers in plain text (questions, "Sorry, I didn't catch that.") or calls the output function `update_list(reply, add, remove, set_quantities, set_usual_quantities, set_buying_patterns, renames, clear)` once, with every change from the sentence and the spoken reply. `update_list` runs the plain tools in a fixed order (clear, remove, add, set quantities, usual quantities, buying patterns, renames), records each in `Deps.tool_calls`, and returns `reply` as the output. No second request is needed to phrase the reply.
4. `run_turn` returns a `turn` event. `events.py` appends it to the log. The caller prints or speaks `said`.

**Why the snapshot is taken once:** Pydantic AI re-renders instructions on every model request inside a run, retries included. A live list read after a retry would show "bread x2", and the model would bump "add another bread" again (found by scenario 3 in v0.1).

**Why retries are safe:** every step of `update_list` is idempotent (adding a Needed item is a no-op, removing a Not needed or missing item is a no-op, a rename that already happened finds nothing, clearing and every setting are absolute), so re-applying a call after a retry changes nothing twice.

### Guards (all Pydantic AI built-ins)

| Guard | What happens |
|---|---|
| Argument validation | `update_list` arguments are typed (quantities `>= 1`, `buying_pattern` is `frequent` or `occasional`). Invalid arguments never reach `tools.py`; the model gets a retry prompt. |
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

**One turn at a time:** `run_turn` holds a process-wide lock (`agent.turn_lock`), so a typed command, a spoken one and a list click never use the SQLite connection at the same time.

## Voice loop (v0.2)

`python -m kiki.voice` runs `Pipeline([mic, *processors(conn), speaker])` on Pipecat's `LocalAudioTransport` at 16 kHz.

| Processor | Job |
|---|---|
| `WakeGate` | Scores every 80 ms of mic audio with openWakeWord's bundled "hey jarvis" model, **always and locally**. While closed it drops the audio, so VAD and Whisper never see it (NFR-0.1). It wakes when a chunk scores `KIKI_WAKE_THRESHOLD` (0.4) or more, and logs every wake and near-miss with its score. On the wake word it plays the listening chime and opens. It closes, silently, when `EndOfTurnDetector` says the command is finished (one command per session) or after `KIKI_LISTEN_TIMEOUT_SECS` with no speech. After each spoken reply (`BotStoppedSpeakingFrame`) it opens again with no wake word and no chime, for `KIKI_FOLLOW_UP_SECS` (5 s), passing audio only from 0.3 s after playback so Kiki's own voice isn't heard; `follow_up` says which kind of session it is ([ADR 0025](docs/adr/0025-listen-after-each-reply-and-ignore-what-is-not-a-command.md), FR-0.18). It doesn't reopen over an interrupted reply. If the wake word comes while Kiki is speaking, it broadcasts an `InterruptionFrame` first, which stops the speech (FR-0.12). |
| `VADProcessor` | Silero VAD. Reports speech starts and every pause of `KIKI_PAUSE_SECS` (0.2 s). |
| `EndOfTurnDetector` | At each pause, asks Smart Turn v3.2 (bundled ONNX model, ~60 ms on CPU) whether the sentence sounds finished from its intonation. Unfinished: hides the pause, so Whisper keeps buffering the same command and the gate stays open. Finished and still silent `KIKI_END_GRACE_SECS` (0.4 s) later, or after `KIKI_MAX_PAUSE_SECS` (3 s) of silence: sends one stop to Whisper and `UserStoppedSpeakingFrame` up to the gate ([ADR 0021](docs/adr/0021-smart-turn-ends-the-command.md), FR-0.14). Speech within the grace period, like the next item after a list comma, keeps the same command ([ADR 0023](docs/adr/0023-grace-period-after-a-finished-sounding-pause.md)). |
| `WhisperSTTService` | Transcribes each speech segment locally with `base.en` and a short grocery-vocabulary `initial_prompt` ([ADR 0019](docs/adr/0019-whisper-base-with-vocabulary-prompt.md)), on `KIKI_WHISPER_THREADS` (8) CPU threads. Pipecat's service doesn't expose the thread count, so `processors()` subclasses it to pass one. |
| `Brain` | Runs `run_turn(transcript, source="voice")` in a thread, pushes the reply as `TTSSpeakFrame`, and logs the turn when the first reply audio plays. A follow-up the agent didn't catch (`DIDNT_CATCH`) is logged with `said` empty and not spoken, so no new window opens (FR-0.18). |
| `PiperTTSService` | Speaks the reply locally. |

Chimes are soft "glass" tones generated in code at 48 kHz (`chime()` in `voice.py`): each note is a sine with gentle 2nd and 3rd harmonics, a click-free attack and a natural ring-out, about 1.2 s and -7 dBFS by default (`KIKI_CHIME_VOLUME`; -10 dBFS went unnoticed, -3 dBFS was too loud). Listening starts with a rising fifth (C6 to G6). Nothing plays when it stops; the reply, or the silence, says it (FR-0.11). The style was picked by ear from three candidates (glass, marimba, bell).

**Voice latency fields** in the `turn` event: `stt` = end of speech → transcript; `llm` = agent run; `tts` = reply ready → first audio; `total` = end of speech → first audio (NFR-0.3). "End of speech" is when `EndOfTurnDetector` decides the command is finished: about 0.66 s after the last word for a finished-sounding sentence (0.2 s pause, ~60 ms check, 0.4 s grace). So the grace period is not in `total`; from the last word, a person waits about 0.66 s more than `total`. `python -m kiki.latency [n]` prints the medians over the last n voice turns from the log.

Measured on this laptop plugged in (2026-10-18, `test_nfr_0_3_*`: synthesized speech, CPU only):

| Stage | Median |
|---|---|
| `stt` (Whisper `base.en`, 8 threads; Whisper itself is ~0.37 s of it, ~0.52 s on 4 threads) | ~0.45 s |
| `llm` (one request; varies ~0.2 s from run to run) | ~1.0 s |
| `tts` (Piper first audio) | ~0.08 s |
| `total` | **~1.5 s** (v0.2 was ~3.0 s) |

**Measure plugged in.** On battery the CPU slows down and Whisper and Piper take about 1.6 times as long: the same test measured `stt` ~0.9 s, `tts` ~0.2 s and `total` ~2.2 s, over NFR-0.3. Daily use is slower than the test because of `llm`: over the last 20 spoken voice turns in the real log, `stt` ~0.57 s, `llm` ~1.6 s (spoken commands are longer and chattier than the test's), `tts` ~0.09 s, `total` ~2.3 s.

**The speaker never idles (FR-0.28):** Pipecat writes to the speaker only while there is sound, unless the output has a mixer. Windows lets an output that gets no data fall asleep, and waking it lost the first ~0.7 s of the next sound ("Milk is added to your list" heard as "your list" in 6 of 8 tries after a 5 to 10 s pause). `KeepSpeakerAwake` in `voice.py` is a mixer that mixes nothing in; with it Pipecat writes silence between sounds, and the reply played whole in 8 of 8 tries.

**Always on:** the pipeline worker runs with `idle_timeout_secs=None`; Pipecat's default would shut it down after a quiet spell.

Only the transcript text crosses the network (to the model API). Audio, the wake model, VAD, Whisper and Piper all run on the laptop (NFR-0.2).

## UI (v0.4)

`python -m kiki.voice` serves the UI at http://127.0.0.1:8765 next to the voice loop; `python -m kiki.ui` serves it alone (text box only, no microphone). Standard library only ([ADR 0020](docs/adr/0020-ui-over-server-sent-events.md)).

| Route | What |
|---|---|
| `GET /` | `ui.html` |
| `GET /speaking-orb.js` | the vendored orb script ([ADR 0024](docs/adr/0024-vendor-the-speaking-orb.md)) |
| `GET /events` | Server-Sent Events: one `snapshot`, then every `state`, `turn` and `list` event; a keep-alive comment every 15 s |
| `POST /command` | `{"text": "..."}` → 202, then the turn runs in a background thread and its events arrive on `/events` |
| `POST /item` | `{"name": "...", "needed": true}` → 200 with the tool result; a click on the list (FR-0.27). Runs `add_items` or `remove_items` under the turn lock, publishes a `list` event, and is not a turn: no model, nothing in the turn log |

The page (v0.10, laid out in [docs/ui.md](docs/ui.md)) is one centered column: the Speaking Orb, the state label, a one-line summary of the last run, the list in two columns (Needed items first, then Not needed Frequent items dimmed; a click flips one), and the text box docked to the bottom of the window. All runs (heard, what changed as chips, what was said, total latency; per-stage latency and raw tool calls under Details) live in a History sheet. The orb's shape follows `state`; each `turn` event's reply is shown as the orb's caption, using estimated word timings so the browser never speaks it; a turn without an error ends on the orb's check mark. The look comes from [DESIGN.md](DESIGN.md) (Framer palette, dark only): every color is a token in `:root`, including the orb's, which the component reads from `--orb-<state>`. Animations stop under reduced motion. Every value from the log is inserted as text, never as HTML.

**Safety, since any web page in the browser could try to reach a local server:**
- Binds to 127.0.0.1 only (NFR-0.6).
- Rejects requests whose `Host` isn't `127.0.0.1` or `localhost` (blocks DNS rebinding).
- `POST /command` and `POST /item` require `Content-Type: application/json`, which other sites can't send without a CORS preflight that the server never answers.
- Commands and item names are 1 to 200 characters; `needed` must be `true` or `false`.

**One Kiki at a time (FR-0.15):** the voice loop and `kiki.ui` bind the UI port first. On Windows the server doesn't set `SO_REUSEADDR` (which there would let a second process share the port), so a second copy fails with "Kiki is already running" before loading any models. Two copies used to both answer every command.

## Matching names

`normalize()` in `tools.py` maps singular and plural to one key with suffix rules: lowercase, collapse spaces, drop a trailing `s` (not `ss`, `us`, `is`), then `ie` to `y` and drop the `e` of `oe`, `che`, `she`, `xe`, `sse`. The key isn't always a real word ("cookie" becomes "cooky"); it only has to match both forms. Irregular plurals ("loaves") aren't handled.

## Data model

One table, `items`: both the Item and its state for the next Order ([ADR 0026](docs/adr/0026-one-item-table-holds-the-next-order-state.md), terms in [CONTEXT.md](CONTEXT.md)). Nothing is ever deleted.

| Column | Type | Notes |
|---|---|---|
| `id` | integer primary key | |
| `name` | text | As the user said it ("eggs") |
| `normalized_name` | text, unique | Lowercase, singular ("egg"). Used for matching |
| `buying_pattern` | `frequent` or `occasional`, default `occasional` | Frequent items always stay on the List |
| `status` | `needed` or `not_needed`, default `needed` | Changes only by command or click; nothing resets it on a schedule |
| `quantity` | integer ≥ 1, default 1 | For the next Order |
| `usual_quantity` | integer ≥ 1, default 1 | A new item's first quantity; re-adding uses it |
| `created_at` | text (ISO 8601) | |
| `updated_at` | text (ISO 8601) | |

**The List** is every Frequent item plus the Needed Occasional ones, Needed first (`read_list`). A Not needed Occasional item is hidden but still known, so "add butter" brings it back at its usual quantity.

**Files from before v0.12:** `db.connect` renames an `items` table without `buying_pattern` to `items_before_v0_12` and starts an empty List. The old rows are kept, not migrated.

## Tools

All tools are plain functions taking and returning JSON-compatible values ([ADR 0008](docs/adr/0008-tools-are-plain-functions.md)). The model never calls them directly; it calls `update_list`, which calls them.

| Tool | Input | Output | Notes |
|---|---|---|---|
| `add_items` | `items: [{name, quantity?}]` | `{added: [...], already_present: [...]}` | A new name is Occasional and Needed. A Not needed item becomes Needed at the quantity said, else its usual. A Needed item is left alone (FR-0.2, FR-0.20) |
| `set_quantity` | `name, quantity` | `{name, quantity}` or `{not_found: name}` | The next Order's quantity, for explicit changes like "make it three"; also makes the item Needed (FR-0.3, FR-0.22). The model computes the new number from the list snapshot |
| `set_usual_quantity` | `name, quantity` | `{name, usual_quantity}` or `{not_found: name}` | "We usually get three tomatoes": usual and next quantity (FR-0.22) |
| `set_buying_pattern` | `name, buying_pattern` | `{name, buying_pattern}` or `{not_found: name}` | Frequent or Occasional (FR-0.23) |
| `rename_item` | `name, new_name` | `{name, new_name}`, `{not_found: name}` or `{error}` | Same item, new name; an error if the new name is another item (FR-0.24) |
| `remove_items` | `names: [string]` | `{removed: [...], not_found: [...]}` | Makes items Not needed, whatever the quantity; already Not needed counts as not found (FR-0.21) |
| `read_list` | none | `{items: [{name, quantity, buying_pattern, status}]}` | The List. Builds the snapshot; not offered to the model, since the snapshot already answers questions (FR-0.19) |
| `clear_list` | none | `{removed: [{name, quantity}]}` | Every item Not needed, no confirmation; returns the ones that were Needed (FR-0.26, [ADR 0012](docs/adr/0012-clear-list-without-confirmation.md)) |

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

- `source` is `text` or `voice`. `stt` and `tts` latencies are `null` in v0.1. `llm` is the whole agent run (model requests plus tool time), so in v0.1 it equals `total`.
- `error` is null, or a short string when the turn failed (for example, no internet).

**`state`**, live only and not logged:

```json
{"type": "state", "value": "idle | listening | thinking | speaking | error"}
```

| Value | Published by | When |
|---|---|---|
| `listening` | `WakeGate` | wake word heard; reply finished (the follow-up window) |
| `thinking` | `WakeGate`, `ui.send_command` | end of a command, before the agent answers |
| `idle` | `WakeGate`, `Brain`, `ui.send_command` | nothing said after the wake word or in the follow-up window; a follow-up that wasn't a command; reply finished |
| `speaking` | `Brain` | first reply audio plays (`BotStartedSpeakingFrame`) |
| `error` | `Brain`, `ui.send_command` | the turn had an `error` (shown until the next state) |

**`list`**, live only: the whole List after every turn and every list click, `{"type": "list", "items": [{"name", "quantity", "buying_pattern", "status"}]}`.

**`snapshot`**, sent once to each UI connection: `{"type": "snapshot", "state", "items", "turns"}` with the last 50 turns from the log.

`events.publish` fans events out to in-process subscribers (one queue per open page). `events.record_turn` is what every caller runs after a turn: append to the log, publish the turn, publish the list.

Adding a field is fine. Renaming or removing one needs an ADR.

## Instructions

The source of truth is `INSTRUCTIONS` in `agent.py`, plus a dynamic line "Current list at the start of this request: ...", one entry per List item: `bread x1 (frequent, needed)`. In short: speak in one or two short sentences with numbers as words; make every change in one `update_list` call; answer questions in plain text; fix obvious speech-to-text slips ("got the X" is often heard as "cut", "dot" or "gut"); every item is frequent or occasional and needed or not needed; add with a quantity only when a number was said; never change a Needed item unless the quantity change is explicit; "remove", "not this time" and "got the X" make an item not needed, never delete it; "we don't buy X any more" makes it occasional and not needed; when asked, read the Needed items, then only the count of Not needed Frequent ones; after clearing say only the count; when unsure reply exactly "Sorry, I didn't catch that." and call no tools.

## Configuration

Environment variables only. A local `.env` is fine (never committed) and is loaded with `uv run --env-file .env ...`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none, required for the default model | Claude API key. Another provider needs its own key (e.g. `OPENAI_API_KEY`) |
| `KIKI_MODEL` | `anthropic:claude-haiku-5-5` | Pydantic AI model string, `provider:model`. Swap with e.g. `openai:<model>`; `test` runs Pydantic AI's offline TestModel |
| `KIKI_DB` | `kiki.db` | SQLite file path |
| `KIKI_LOG` | `logs/turns.jsonl` | Turn log path |
| `KIKI_WAKE_THRESHOLD` | `0.4` | openWakeWord score (0–1) that counts as "hey jarvis". Raise if it wakes by itself, lower if it misses you. The terminal logs every wake (`wake word heard (score 0.99)`) and every near-miss (`almost heard the wake word (score 0.42, needs 0.50)`), so you can see how close a missed "hey jarvis" came |
| `KIKI_LISTEN_TIMEOUT_SECS` | `6` | How long the gate stays open after the wake word if nobody speaks |
| `KIKI_FOLLOW_UP_SECS` | `5` | How long Kiki listens after each reply for another command without the wake word |
| `KIKI_PAUSE_SECS` | `0.2` | A pause this long makes Smart Turn check whether the sentence sounds finished |
| `KIKI_END_GRACE_SECS` | `0.4` | After a pause sounds finished, how long to wait for more words before closing (list commas) |
| `KIKI_MAX_PAUSE_SECS` | `3` | Silence that ends a command even if it sounded unfinished |
| `KIKI_WHISPER_MODEL` | `base.en` | faster-whisper model name. `small.en` is more robust but adds about 1.1 s |
| `KIKI_WHISPER_THREADS` | `8` | CPU threads for Whisper, one per core of this laptop. faster-whisper's own default is 4, about 0.15 s slower; more threads than cores is slower again |
| `KIKI_CHIME_VOLUME` | `0.45` | Peak level of the listening chime, 0 to 1 (about -7 dBFS by default) |
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
| Speaking Orb (`src/kiki/speaking-orb.js`, vendored, MIT, Ship Notes) | The UI's orb ([ADR 0024](docs/adr/0024-vendor-the-speaking-orb.md)). One file, no network, no build; Kiki's one change is reading its colors from DESIGN.md tokens | v0.10 |

`piper-tts` is GPL-3.0. Fine for a personal assistant; if Kiki is ever distributed, switch to `PiperHttpTTSService` or Kokoro.

Apart from the vendored orb, the UI adds no dependencies: `http.server`, Server-Sent Events and one HTML file.

## Testing

- `test_tools.py`, `test_events.py`, `test_agent.py`: deterministic, no network. Always run. `test_agent.py` scripts the model with Pydantic AI's `FunctionModel`, so it checks what the model is sent, retries and guards without an API call.
- `test_voice.py`: the gate tests use a fake detector and are instant. Real-model tests put `RealTimeMic` first, which releases audio at real-time pace: Smart Turn and VAD keep wall-clock time, and audio pushed all at once hid the list-comma problem. Waits are streamed silence, never `SleepFrame`, because a real mic keeps sending silence and the 3 s fallback counts it. Tests marked `voice` run the real wake word, Silero, Whisper and Piper on speech synthesized by Piper ([ADR 0017](docs/adr/0017-test-voice-with-synthesized-speech.md)); `test_scenario_by_voice` (also marked `scenario`) speaks the seven v0.2 scenarios and v0.12 scenarios 13, 16 and 22 to the real agent. First run downloads the Whisper and Piper models.
- `test_latency.py`: the log report. `test_voice.py::test_nfr_0_3_*` (marked `voice` and `scenario`) speaks twenty commands through the full chain to the real agent and requires a median `total` of 2 s or less.
- `test_ui.py`: real HTTP against a server on a random port with a scripted model: the page, the orb script served locally, the live event sequence for a typed command (`thinking`, `turn`, `list`, `idle`), past runs in the snapshot, list clicks (`POST /item`), localhost binding, and the Host, content-type and length checks.
- `test_scenarios.py`: sends each ROADMAP scenario to the real model and asserts on tool calls and final list state, not on exact wording. A full run is 23 short Haiku turns, about a cent. Needs `ANTHROPIC_API_KEY`; skipped automatically without it, or deselect with `-m "not scenario"`.
