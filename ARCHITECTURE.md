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
  Tab5 item sheet  ──> POST /item    ──> also set_quantity / rename_item (v0.16)

v0.14 (Tab5: a thin client of the laptop over the home Wi-Fi)
  Tab5 mic ──UDP :8768──> Tab5Mic ──> WakeGate ... PiperTTSService ──> Tab5Speaker ──TCP :8769──> Tab5 speaker
  ui.html in a headless Chrome ──screen.py──JPEG frames, TCP :8767──> Tab5 screen
  Tab5 touches ──"down|move|up x y"──> screen.py ──> touch events in the page

v0.17 (ordering: Instacart through a Kiki extension in the owner's own Chrome)
  "order the groceries" ──> update_list ──> ordering.py ──> instacart.run_job
      ──> chrome.exe opens instacart.com/...#kiki-<job>-<port> in the running Chrome
      ──> browser/instacart/worker.js: GET /instacart/job, does it in that tab, POST /instacart/result
  past Orders ──> orders, order_lines, products (kiki.db) ──> one Claude request matches Items to Products

v0.19 (the Cart filling, live on the Tab5)
  Kiki's tab ──chrome.debugger screencast──> worker.js ──POST /instacart/frame──> Kiki keeps the newest
      ──GET /instacart/frame, while "Filling cart"──> Tab5 decodes it where the orb is
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
| Device (v0.14) | M5Stack Tab5, an Arduino sketch in `device/stream`, built with arduino-cli | [0032](docs/adr/0032-device-code-lives-in-this-repo.md) |
| Device links | Plain sockets opened by the Tab5: screen TCP 8767, mic UDP 8768, speaker TCP 8769 | [0027](docs/adr/0027-the-tab5-is-a-thin-client-over-the-home-network.md), [0029](docs/adr/0029-tab5-mic-over-udp-speaker-over-tcp-paced-by-the-clock.md) |
| Device screen | The UI drawn natively by the Tab5 with LVGL (`device/kiki`); the streamed page (`device/stream`) remains an alternative | [0033](docs/adr/0033-draw-the-ui-natively-on-the-tab5.md), [0028](docs/adr/0028-stream-the-real-ui-page-to-the-tab5.md) |
| Device audio | Mic and speaker take turns; volume in the samples under a fixed ceiling | [0030](docs/adr/0030-the-tab5-mic-and-speaker-take-turns.md), [0031](docs/adr/0031-tab5-volume-in-the-samples-under-a-fixed-ceiling.md) |
| Store (v0.17) | Instacart (Wegmans), through Kiki's own Chrome extension in the owner's signed-in Chrome; Kiki fills the Cart, the owner checks out | [0034](docs/adr/0034-reach-instacart-through-a-kiki-extension-in-the-owners-chrome.md) |
| Products (v0.17) | Learned from what was placed in past Orders; Claude says which Products are which Item, code picks the most ordered | [0035](docs/adr/0035-learn-each-items-product-from-what-was-placed.md) |

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
  stt_bench.py  speech-to-text models side by side on Piper-spoken commands: time and word accuracy
  voice.py    voice loop (v0.2): WakeGate, Brain, the processor chain, the mic/speaker runner;
              Tab5Mic and Tab5Speaker (v0.14)
  screen.py   streams the UI page to the Tab5 and replays its touches (v0.14)
  screen_keyboard.js  the on-screen keyboard injected into the page streamed to the Tab5
  ordering.py the ordering flows (v0.17): read new Orders, match Items to Products, fill the Cart
  instacart.py  Kiki's side of the extension (v0.17): one job at a time, opened as a Chrome tab
browser/instacart/  the Kiki for Instacart extension (v0.17, ADR 0034): manifest.json, worker.js
device/       the Tab5's programs, one Arduino sketch per folder (v0.14, ADR 0032)
  check/      screen, touch, mic and speaker check
  stream/     the Tab5 program: streamed screen, touch, mic, speaker, volume bar
  kiki/       the native Tab5 program (v0.15, ADR 0033): the UI drawn with LVGL, same audio;
              build.ps1, lv_conf.h, src/ (Inter fonts and their OFL licence)
              (secrets.h: Wi-Fi and the laptop's IP, git-ignored; secrets.h.example committed)
tests/
  test_tools.py       tools.py against a temp SQLite file
  test_events.py      turn log format
  test_agent.py       agent loop against Pydantic AI's FunctionModel / TestModel
  test_scenarios.py   ROADMAP scenarios against the real Claude API (marked `scenario`)
  test_latency.py     latency report
  test_ui.py          UI server over real HTTP with a scripted model
  test_voice.py       wake gate with a fake detector; real models on Piper-synthesized speech (marked `voice`)
  test_tab5.py        the laptop's side of the Tab5's links, over real sockets
  test_ordering.py    ordering with a fake extension and a fake matcher (v0.17)
  conftest.py         `speak`: Piper-synthesized speech for the voice tests
```

`src/` layout is uv's default for a package (`uv init --lib`).

## Request flow (one turn)

1. A command arrives as text (typed in v0.1, transcribed in v0.2).
2. `run_turn` snapshots the list once, then calls `agent.run_sync` with only the command. The model sees the static instructions, the snapshot and the command. No previous turns ([ADR 0009](docs/adr/0009-single-turn-commands.md)).
3. **One model request** ([ADR 0018](docs/adr/0018-one-model-request-per-command.md)). The model either answers in plain text (questions, "Sorry, I didn't catch that.") or calls the output function `update_list(reply, add, remove, set_quantities, set_usual_quantities, set_buying_patterns, renames, clear, learn_product_preferences, fill_cart, set_products, forget_products)` once, with every change from the sentence and the spoken reply. `update_list` runs the plain tools in a fixed order (clear, remove, add, set quantities, usual quantities, buying patterns, renames, then the ordering steps: forget products, set products, analyze, fill the Cart), records each in `Deps.tool_calls`, and returns `reply` as the output. No second request is needed to phrase the reply. When an ordering step ran, Kiki writes the reply itself from what happened (see [Ordering](#ordering-v017)); the model can't know the result when it writes `reply`.
4. `run_turn` returns a `turn` event. `events.py` appends it to the log. The caller prints or speaks `said`.

**Why the snapshot is taken once:** Pydantic AI re-renders instructions on every model request inside a run, retries included. A live list read after a retry would show "bread x2", and the model would bump "add another bread" again (found by scenario 3 in v0.1).

**Why retries are safe:** every step of `update_list` is idempotent (adding a Needed item is a no-op, removing a Not needed or missing item is a no-op, a rename that already happened finds nothing, clearing and every setting are absolute), so re-applying a call after a retry changes nothing twice.

### Guards (all Pydantic AI built-ins)

| Guard | What happens |
|---|---|
| Argument validation | `update_list` arguments are typed (quantities `>= 1`, `buying_pattern` is `frequent` or `occasional`). Invalid arguments never reach `tools.py`; the model gets a retry prompt. |
| Tool errors | A tool result with an `error` key is raised as `ModelRetry`, so the model sees the message and can correct itself. The call is still logged. |
| Output guard | `spoken_style` output validator rejects markdown, bullets, underscores and digits with a retry, for plain-text replies and for the `reply` of `update_list` (FR-0.10). Empty replies are retried by Pydantic AI itself. Kiki's own ordering replies pass as they are: a retry would run the ordering again, and a Product's name may hold digits. |
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

Tools that ran before a failure stay in `tool_calls`, so the log still shows them (for example, a `clear_all_items` that ran before the connection dropped).

**SQLite and threads:** Pydantic AI runs sync functions in worker threads and voice turns run in a thread too, so `db.connect` uses `check_same_thread=False`. Only one `update_list` runs per turn and turns are sequential, so the connection is never used concurrently.

**Model client:** built per turn with `infer_model`. `warm_up()` builds one at startup (voice, terminal, UI) to pay the one-time cost of about three seconds before the first command. A client must not be cached across turns: its connections belong to the event loop of the thread that first used it, and a turn on another thread (the UI and voice both use worker threads) then stalls until the request timeout. That cost 11 s per turn until v0.4.

**One turn at a time:** `run_turn` holds a process-wide lock (`agent.turn_lock`), so a typed command, a spoken one and a list click never use the SQLite connection at the same time.

## Voice loop (v0.2)

`python -m kiki.voice` runs `Pipeline([mic, *processors(conn), speaker])` at 16 kHz. The mic and the speaker are Pipecat's `LocalAudioTransport`, or the Tab5's (`Tab5Mic` with `KIKI_MIC=tab5`, `Tab5Speaker` with `KIKI_SPEAKER=tab5`, see [Tab5](#tab5-v014)).

| Processor | Job |
|---|---|
| `WakeGate` | Scores every 80 ms of mic audio with openWakeWord's bundled "hey jarvis" model, **always and locally**. While closed it drops the audio, so VAD and Whisper never see it (NFR-0.1). It wakes when a chunk scores `KIKI_WAKE_THRESHOLD` (0.5) or more, and logs every wake and near-miss with its score. On the wake word it plays the listening chime and opens. It closes, silently, when `EndOfTurnDetector` says the command is finished (one command per session) or after `KIKI_LISTEN_TIMEOUT_SECS` with no speech. After each spoken reply (`BotStoppedSpeakingFrame`) it opens again with no wake word and no chime, for `KIKI_FOLLOW_UP_SECS` (5 s), passing audio only from 0.3 s after playback so Kiki's own voice isn't heard; `follow_up` says which kind of session it is ([ADR 0025](docs/adr/0025-listen-after-each-reply-and-ignore-what-is-not-a-command.md), FR-0.18). It doesn't reopen over an interrupted reply. If the wake word comes while Kiki is speaking, it broadcasts an `InterruptionFrame` first, which stops the speech (FR-0.12). |
| `VADProcessor` | Silero VAD. Reports speech starts and every pause of `KIKI_PAUSE_SECS` (0.2 s). |
| `EndOfTurnDetector` | At each pause, asks Smart Turn v3.2 (bundled ONNX model, ~60 ms on CPU) whether the sentence sounds finished from its intonation. Unfinished: hides the pause, so Whisper keeps buffering the same command and the gate stays open. Finished and still silent `KIKI_END_GRACE_SECS` (0.4 s) later, or after `KIKI_MAX_PAUSE_SECS` (3 s) of silence: sends one stop to Whisper and `UserStoppedSpeakingFrame` up to the gate ([ADR 0021](docs/adr/0021-smart-turn-ends-the-command.md), FR-0.14). Speech within the grace period, like the next item after a list comma, keeps the same command ([ADR 0023](docs/adr/0023-grace-period-after-a-finished-sounding-pause.md)). |
| `WhisperSTTService` | Transcribes each speech segment locally with `base.en` and a short grocery-vocabulary `initial_prompt` ([ADR 0019](docs/adr/0019-whisper-base-with-vocabulary-prompt.md)), on `KIKI_WHISPER_THREADS` (8) CPU threads. Pipecat's service doesn't expose the thread count, so `processors()` subclasses it to pass one. |
| `Brain` | Runs `run_turn(transcript, source="voice")` in a thread, pushes the reply as `TTSSpeakFrame`, and logs the turn when the first reply audio plays. If a command ends and Whisper finds no words within `NO_WORDS_SECS` (3 s), it sets the state back to idle, which nothing else would. A follow-up the agent didn't catch (`DIDNT_CATCH`) is logged with `said` empty and not spoken, so no new window opens (FR-0.18). |
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

Audio stays in the home (NFR-0.8): with the laptop's mic it never leaves the laptop, with the Tab5 it travels only between the Tab5 and the laptop. The wake model, VAD, Whisper and Piper all run on the laptop; only the transcript text goes to the model API.

## UI (v0.4)

`python -m kiki.voice` serves the UI at http://127.0.0.1:8765 next to the voice loop; `python -m kiki.ui` serves it alone (text box only, no microphone). Standard library only ([ADR 0020](docs/adr/0020-ui-over-server-sent-events.md)).

| Route | What |
|---|---|
| `GET /` | `ui.html` |
| `GET /speaking-orb.js` | the vendored orb script ([ADR 0024](docs/adr/0024-vendor-the-speaking-orb.md)) |
| `GET /events` | Server-Sent Events: one `snapshot`, then every `state`, `turn` and `list` event; a keep-alive comment every 15 s |
| `POST /command` | `{"text": "..."}` → 202, then the turn runs in a background thread and its events arrive on `/events` |
| `POST /item` | `{"name": "...", "needed": true}`, `{"name": "...", "quantity": 3}`, `{"name": "...", "buying_pattern": "frequent"}`, `{"name": "...", "new_name": "..."}` or `{"name": "...", "forget_product": true}` → 200 with the tool result; a click on the list (FR-0.27) or an edit in the Tab5's item sheet (FR-0.33, FR-0.34). Runs `add_items`, `remove_items`, `set_quantity`, `set_buying_pattern`, `rename_item` or `forget_product_for_item` under the turn lock, publishes a `list` event, and is not a turn: no model, nothing in the turn log. 409 when the tool refuses (a name that's taken), 404 when a quantity or name is for an unknown item, 400 unless exactly one change is given (quantity 1–99) |
| `POST /reset` | `{}` → 200 with `reset_list`'s result: the Reset button, after its second tap (FR-0.35). Logged as a turn with `source: "button"` and the List as it was in `args.before`, so History shows it and the log can undo it |
| `GET /instacart/job` | the job waiting for the extension, or 204 (v0.17, ADR 0034) |
| `POST /instacart/result` | the extension's answer, `{id, ok, data}` or `{id, ok: false, error}`; ignored unless `id` is the waiting job's |
| `POST /instacart/progress` | `{id, done, total}` while the Cart fills; published as a `progress` event |
| `POST /instacart/frame` | `{id, data}`, a base64 JPEG of Kiki's tab while the Cart fills (v0.19, FR-0.42); kept only if `id` is the waiting job's and it's a JPEG of at most 256 KB, replacing the last one; 400 if `data` isn't base64 |
| `GET /instacart/frame` | the newest of those frames as `image/jpeg`, or 204 when no job is running or none came yet; cleared when each job starts and ends |

The page (v0.10, laid out in [docs/ui.md](docs/ui.md)) is one centered column: the Speaking Orb, the state label, a one-line summary of the last run, the list in two columns (Needed items first, then Not needed Frequent items dimmed; a click flips one), and the text box docked to the bottom of the window. All runs (heard, what changed as chips, what was said, total latency; per-stage latency and raw tool calls under Details) live in a History sheet; an ordering run adds a Products row, one line per item with its Product, guess or failure (v0.17). The orb's shape follows `state`; each `turn` event's reply is shown as the orb's caption, using estimated word timings so the browser never speaks it; a turn without an error ends on the orb's check mark. The look comes from [DESIGN.md](DESIGN.md) (Framer palette, dark only): every color is a token in `:root`, including the orb's, which the component reads from `--orb-<state>`. Animations stop under reduced motion. Every value from the log is inserted as text, never as HTML.

**Safety, since any web page in the browser could try to reach a local server:**
- Binds to 127.0.0.1, unless `KIKI_UI_HOST` opens it to the home network for a Tab5 program that follows `/events` itself (NFR-0.7, [ADR 0027](docs/adr/0027-the-tab5-is-a-thin-client-over-the-home-network.md)). There is no password yet.
- Rejects requests whose `Host` isn't `localhost` or an IP address (blocks DNS rebinding: an IP can't be rebound to another site, and the Tab5 addresses the laptop by its IP).
- Every `POST` requires `Content-Type: application/json`, which other sites can't send without a CORS preflight that the server never answers. The extension can, because its host permission covers `http://localhost/*`.
- Commands and item names are 1 to 200 characters; `needed` must be `true` or `false`.

**One Kiki at a time (FR-0.15):** the voice loop and `kiki.ui` bind the UI port first. On Windows the server doesn't set `SO_REUSEADDR` (which there would let a second process share the port), so a second copy fails with "Kiki is already running" before loading any models. Two copies used to both answer every command.

## Tab5 (v0.14)

An M5Stack Tab5 (ESP32-P4, 720×1280 touchscreen, two mics, 1 W speaker, Wi-Fi through an ESP32-C6) on the fridge is Kiki's screen, mic and speaker. It is only a client: it opens every link to the laptop, whose IP and the Wi-Fi it reads from `device/stream/secrets.h` ([ADR 0027](docs/adr/0027-the-tab5-is-a-thin-client-over-the-home-network.md)). Everything else still runs on the laptop.

**Running it:** flash `device/stream` once (below), then on the laptop:

```powershell
$env:KIKI_MIC="tab5"; $env:KIKI_SPEAKER="tab5"; uv run --env-file .env python -m kiki.voice
uv run python -m kiki.screen        # in a second terminal, once Kiki is up
```

The Tab5 joins the Wi-Fi at power-on and keeps retrying each link every 3 s, so start order doesn't matter to it. The laptop must stay awake and keep its IP (reserve it in the router).

| Link | Direction | Transport, port | What travels | Laptop side | Tab5 side |
|---|---|---|---|---|---|
| Screen | laptop → Tab5 | TCP 8767 | 4-byte big-endian length, then a JPEG of the page, 720×1200 | `screen.py`: `PageStreamer.serve_tab5` | `receiveFrames`, `decodeAndShowFrame` |
| Screen acks and touches | Tab5 → laptop | same connection | `shown` after each frame; `down x y`, `move x y` (≤30/s), `up x y` | replayed with `Input.dispatchTouchEvent` | `handleTouch` |
| Mic | Tab5 → laptop | UDP 8768 | 20 ms per packet: 320 samples, 16 kHz mono int16 | `voice.Tab5Mic` | `sendMicPacketsTask` |
| Speaker | laptop → Tab5 | TCP 8769 | 16 kHz mono int16, paced to real time, 0.15 s ahead | `voice.Tab5Speaker` | `playKikiAudioTask` |

**Screen** ([ADR 0028](docs/adr/0028-stream-the-real-ui-page-to-the-tab5.md), FR-0.31): `python -m kiki.screen` starts a headless Chrome (`KIKI_CHROME`), sizes the page like the Tab5 with touch emulation on, loads `http://127.0.0.1:<KIKI_UI_PORT>/` and starts the DevTools screencast (JPEG, `KIKI_SCREEN_QUALITY` 70). Chrome sends a frame on every repaint, about 12 a second while the orb moves, 25–35 KB each. Each Tab5 connection is sent the newest frame at once, then the newest again only after `shown`, so a slow link skips frames instead of queueing them. The Tab5 decodes a frame in hardware in ~9 ms and shows it in ~80 ms. The page is 720×1200 in the panel's own portrait orientation (rotated to landscape, showing a frame took 767 ms instead of 78 ms); the Tab5 draws its volume bar in the bottom 80 px. The decoder writes big-endian RGB565 (`JPEG_DEC_RGB_ELEMENT_ORDER_RGB`), which is what M5GFX's `pushImage` expects.

**On-screen keyboard** (FR-0.32): a headless Chrome has no keyboard, so `screen.py` injects `screen_keyboard.js` into the page it streams, and only there: it opens when the text box is focused, lifts the docked box above itself, types into it, and Send submits the form. Chrome runs scripts added with `Page.addScriptToEvaluateOnNewDocument` only once `Page.enable` has been sent, which the first version missed.

**Mic** ([ADR 0029](docs/adr/0029-tab5-mic-over-udp-speaker-over-tcp-paced-by-the-clock.md), FR-0.29): M5Unified records 20 ms at a time into a ring of 16 buffers (320 ms of slack); its capture task hands each full buffer to `sendMicPacketsTask` and queues the next. That task sends one UDP packet per buffer, whatever the screen is doing. Two settings keep it lossless: Wi-Fi power saving is off (it dropped a quarter of the packets, with gaps of 40 s), and the USB log never waits for a reader (`Serial.setTxTimeoutMs(0)`; a 2 s wait froze the mic whenever nothing was reading). `Tab5Mic` logs `Tab5 mic sent N packets in 10 s`; 500 means none lost.

**Speaker** (FR-0.30): `Tab5Speaker` accepts the Tab5's connection (a new one replaces the old) and writes each 40 ms chunk, pacing itself against `_played_by`, the time the Tab5 will have played everything sent, so it stays `LEAD_SECS` (0.15 s) ahead without drifting; sleeping one chunk per chunk fell behind on Windows and made replies choppy. With the Tab5 speaker the pipeline's output rate is 16 kHz, so Piper speaks at that rate and only the 48 kHz chime is resampled. The Tab5 buffers up to 4 s, starts once 160 ms are in, keeps two chunks queued, and logs `played N ms, G gaps` after each reply.

**Taking turns** ([ADR 0030](docs/adr/0030-the-tab5-mic-and-speaker-take-turns.md)): M5Unified drives the mic and the speaker as two I2S channels with separate clocks on the same pins, and running both at once played garbled, loud noise. So the mic runs by default; when Kiki's audio arrives the Tab5 calls `switchToSpeaker`, and 200 ms after the last sample has played, `switchToMic`. While the Tab5 speaks it can't hear "hey jarvis", and the chime pauses the mic for about half a second.

**Volume** ([ADR 0031](docs/adr/0031-tab5-volume-in-the-samples-under-a-fixed-ceiling.md)): M5Unified's output is `sample × 2 × magnification × master² × channel² / 2³⁶`, clipped. It is fixed at magnification 8 and master and channel 255, where a full-scale sample comes out at 0.98 of the range. `makeLouderAtVolume` then boosts each chunk 2×, limits it to 0.95 of full scale (instant attack, 60 ms release), and scales it by the volume bar. The bar is the Tab5's own (touches on it never reach the page), linear, saved in `Preferences` (`kiki`/`vol`), and starts at 5%.

**The Tab5 program** (`device/stream/stream.ino`): `setup` starts the JPEG decoder, the mic, `sendMicPacketsTask`, `playKikiAudioTask` and the Wi-Fi; `loop` handles touches and the screen link. Test commands over USB serial (115200): `tap x y` taps the page like a finger, `shot` sends the screen as raw RGB (the only time the log waits for the reader). Every link logs to the serial monitor.

**Native UI** (v0.15, `device/kiki`, [ADR 0033](docs/adr/0033-draw-the-ui-natively-on-the-tab5.md)): the alternative to the streamed page. The Tab5 draws the UI itself with LVGL 9.6 and needs no Chrome and no `kiki.screen`; it follows Kiki's events itself, so Kiki must run with `KIKI_UI_HOST=0.0.0.0`. `secrets.h` adds `KIKI_PORT` (Kiki's UI port) and `KIKI_TZ` (a POSIX time zone for run times).

| File | What |
|---|---|
| `kiki.ino` | setup, the main loop and its stall log, the shared state and the serial test commands (`tap`, `tapitem`, `tapsheet`, `tapreset`, `key`, `drag`, `shot`, `silence`, `redraw`, `orbspeak`, and `live on`/`live off` for the Cart-filling view without a fill) |
| `events.ino` | `networkTask`: `GET /events` and the `POST /item`, `POST /reset` and `POST /command` requests; the loop turns its events (snapshot, state, list, turn, progress) into the screen's state, and holds Kiki's List while edits are on their way |
| `sheet.ino` | the item sheet (FR-0.33): this order's quantity and Needed, Frequent or Occasional, the Product with Forget (FR-0.34), rename, remove; built once at start-up (rename mode and its keyboard too, hidden), slid up from below the screen |
| `screen.ino`'s keyboard | `makeKeyboard`: our own layout on an LVGL button matrix (LVGL's keyboard widget types its key labels, and ours say "space" and "Send"); three layers, one-shot shift, a key handler that sends `LV_EVENT_READY` (action key) or `LV_EVENT_CANCEL` (hide key) to its text box; the white action key and the quiet keys' small labels are drawn in a draw-task event. `key <name>` over serial presses a key through the same handler |
| `serial.ps1` | sends test commands over USB serial and prints the log: `serial.ps1 "tapitem 0" "wait 2" "tapsheet plus" ...` |
| `shot.ps1` | saves what the Tab5 shows as a PNG through the `shot` command: `shot.ps1 -Out sheet.png "tapitem 0" "wait 1.5"` |
| `screen.ino` | the UI from docs/ui.md in DESIGN.md's tokens at 1.5× the web's sizes: top bar, state, caption, last run, List with its two-tap Reset, F or O on each row and "Not on the list" (v0.18; the card stops at four and a half rows), text box and keyboard, History sheet, volume bar |
| `orb.ino` | the Speaking Orb's particle field and shapes, ported; the speaking pulse from the reply's words |
| `live.ino` | the Cart filling, live (v0.19, FR-0.42): from the first `progress` event until a state other than thinking, the orb hides and `networkTask` fetches `GET /instacart/frame` every 150 ms (the next only once the loop has shown the last); the loop decodes it with ESP-IDF's hardware JPEG decoder and the PPA puts it in the orb's 720×360 slot, centered. Meanwhile the screen is view only: the keyboard, History and the item sheet close (a rename being typed is dropped, a settling quantity is sent), any press in progress is let go, and a clear blocker on the top layer takes every touch but the volume bar's. The orb stays off for the whole time in `showNewestOrbFrame` itself, since closing any of those turns it back on. The fill's `turn`, any state but thinking, or a dropped event stream ends it |
| `audio.ino` | mic and speaker, as in `device/stream` |

The orb draws 3,000 particles at half resolution in its own task on core 0, into bands of rows in internal RAM, with lookup tables for sine and the rings and single-precision maths only (Arduino's `PI` is a double and forced software maths); the P4's PPA scales each frame 2× straight into the panel's framebuffer. LVGL redraws only what changes and leaves the orb's rectangle alone; the orb pauses while History or the keyboard covers it. The speaking pulse comes from the reply's words with the web's syllable estimate, its clock restarting when the Tab5 actually starts playing. Measured on the Tab5 (2026-10-22):

| | Before (first port) | After |
|---|---|---|
| Orb, listening / thinking | 44 ms a frame, ~21 fps | ~21 ms, ~40 fps |
| Orb, speaking | slower | ~24 ms, ~36 fps |
| Tap → keyboard open | 442 ms | 17 ms |
| Tap → item flipped | 119 ms | 10 ms |
| Tap → History open | didn't open | 130–137 ms |
| Mic packets per 10 s | 502 | 502 |

**Nothing on the screen waits on the network** (v0.16): `loop()` draws (touch, orb, LVGL) and never touches Wi-Fi. `networkTask` keeps the event stream open, reads its lines and sends the POSTs, and talks to the loop through three FreeRTOS queues: event lines in, requests out, results back; only the loop touches LVGL and the screen's state. Edits change the screen first and then queue their request (below); a command that wasn't taken goes back into the text box with the reason. Every 5 s the loop logs its slowest step (`[loop] slowest step 4 ms (orb), 2100 loops in 5 s`). Measured on the Tab5 (2026-10-22, `serial.ps1 "tapitem 0"`):

| | Before | After |
|---|---|---|
| Tap → flipped row on the panel | 94–126 ms (after Kiki answered) | 9–12 ms |
| Tap → first pixels | 90–112 ms | 14–28 ms |
| Slowest loop step around a tap | 102–106 ms (the POST, inside LVGL's tap handler) | 33–37 ms (rebuilding the List when Kiki's new List arrives) |
| Slowest loop step while Kiki is offline | each retry could block 0.5 s (connect timeout) | 4–6 ms |

**Edits** (FR-0.33): every change in the item sheet (`sheet.ino`) updates `items` and the row at once, then queues its request. While any edit is on its way (or the stepper hasn't been still for 350 ms), Kiki's `list` events are held and only the newest is kept; when the last edit is answered it's shown, and if an edit failed and no newer List came, `serverItems` (Kiki's List as last sent) comes back. Holding the List keeps an older List, arriving between two quick taps, from flicking a row back and forth. `showList` updates the rows in place when their count is unchanged and rebuilds them only when it changes (3–8 ms). The sheet is built once at start-up, parked below the screen and only slid; it has no dimmed backdrop, because a full-screen redraw takes ~78 ms here. The orb pauses only while the sheet moves. Measured on the Tab5 (2026-10-23, `serial.ps1 "tapitem 0" "tapsheet plus" ...`):

| | |
|---|---|
| Tap → the sheet's first frame | 3–4 ms |
| Tap on –, +, Needed, Not needed → on the panel | 4–9 ms |
| Quick stepper taps | one request, 350 ms after the last |
| Sheet slide, opening / closing | 5 frames in ~280 ms (~55 ms a frame) / 6–7 frames in ~225 ms, for the redesigned sheet (~760 px tall); the first, shorter sheet took 7 frames to open |

The opening slide is the slowest thing left: each frame redraws the whole visible sheet in software into a PSRAM buffer and copies it to the panel (~16 ms of the 55), so a taller sheet slides slower. Sliding a once-drawn picture of the sheet instead of redrawing its widgets each frame is the likely next step. LVGL's PPA draw unit would take the drawing to hardware, but in LVGL 9.6 it calls `esp_cache_get_line_size_by_addr`, which this Arduino core's ESP-IDF doesn't have.

**Arduino and prototypes:** Arduino puts its generated prototypes before the first line that looks like a function used as a pointer, and a comment like `// built once (buildItemSheet)` on a declaration counts. That put them above `struct Item` and broke the build; keep `(` followed by a function's name out of comments on declarations.

Lessons: 168 KB of static buffers in internal RAM starved Wi-Fi and the speaker's DMA and rebooted the Tab5 when Kiki spoke (the particles now live in PSRAM); a part chunk left in the speaker FIFO kept the mic paused for good (both programs now drop it after 200 ms with no new audio); a screenshot over USB freezes the screen for seconds, so none are taken during live replies. Build and flash with `powershell -ExecutionPolicy Bypass -File device\kiki\build.ps1 -Port COM9` (it adds the sketch folder to the include path so LVGL finds `lv_conf.h`).

**Building and flashing** ([ADR 0032](docs/adr/0032-device-code-lives-in-this-repo.md)): copy `secrets.h.example` to `secrets.h` in the sketch folder and fill it in, then

```bash
arduino-cli compile --upload -p COM9 -b m5stack:esp32:m5stack_tab5:CDCOnBoot=cdc device/stream
```

The port is whatever the Tab5 shows up as (`arduino-cli board list`). If an upload can't connect, hold Reset for 2 s until the green LED blinks fast (download mode), upload, then press Reset once to start the program. `device/check` is a standalone check of the screen, touch, mic and speaker.

### Tab5 memory

The Tab5's Wi-Fi is an ESP32-C6 on SDIO, and its receive buffers come from the P4's internal RAM. `setup()` calls `heap_caps_malloc_extmem_enable(0)` first, so every ordinary allocation (LVGL's objects, styles and text, `String`s, the History runs) goes to PSRAM; drivers that need internal or DMA memory ask for it by capability. Before (v0.18), with 22 List rows and History's ordering rows built, internal RAM fell to 24-31 KB and the SDIO driver asserted (`sdio_rx_get_buffer sdio_drv.c:953`) and rebooted, usually right after "hey jarvis" when the speaker took its share. After: 110-150 KB free, History open included, the orb unchanged at 40 fps. Every `[events]` line in the serial log prints the free internal RAM and its largest block. Scrolling History stalls the loop (about 25 passes in 5 s, steps up to 250 ms) with or without this; it's a full redraw of the sheet, not memory.

## Ordering (v0.17)

Kiki fills the Store's Cart; the owner checks out in the Instacart app. Kiki never places or pays for an order (NFR-0.10).

**How Kiki reaches Instacart** ([ADR 0034](docs/adr/0034-reach-instacart-through-a-kiki-extension-in-the-owners-chrome.md)). The owner loads `browser/instacart` once in their own Chrome (`chrome://extensions`, Developer mode, Load unpacked). `instacart.run_job(kind, **payload)` stores one job, then runs `chrome.exe https://www.instacart.com/store/account/orders#kiki-<job id>-<port>`, which opens a tab in the running Chrome (or starts it, signed in). The extension's service worker sees that tab, fetches the job from `GET /instacart/job`, does it in that tab only, posts `POST /instacart/result` and closes the tab. It runs its page steps with `chrome.scripting.executeScript` in the page's own world, where Instacart's data is (`window.__APOLLO_CLIENT__`). No Allow dialog, no second profile, no Claude tokens. `run_job` waits up to five minutes; no answer is `no_answer` (the extension isn't loaded, or Chrome is stuck).

| Job | What the extension does | Returns |
|---|---|---|
| `read_orders {known}` | Reads the first page of the order history (10 orders), then each delivered Order from the Store it doesn't know | `{orders: [{id, retailer, address, delivered_at, state, list_items, lines: [{status, quantity, quantity_type, product_id, product_name}]}]}` |
| `search {query}` | The Store's search page | `{results: [{id, name, bought}]}`, the top five; `bought` when the page tags it "Buy it again" |
| `reload` | Answers, closes the tab, then reloads the extension from disk (`chrome.runtime.reload`): after an edit to `browser/instacart`, no trip to `chrome://extensions` | `{}` |
| `fill_cart {address, lines: [{item, product_id, query, quantity}]}` | For each line: the Product's page (or a search result when it has none: the first one tagged "Buy it again", else the first), waits up to 10 s for the address in the page's header, presses **Add to cart** (one), then sets the exact count in the "N in cart" menu ("6", "6 ct" or "6 pkgs", by how the Product is sold) and reads it back. A sold-out Product falls back to another search result | `{lines: [{..., status: added \| top_match \| failed, reason, product_id, product_name}]}` |

What the page gives, per line of an Order: `item` is what was placed, `currentItem` is what came (a substitute when `status` is `replaced`), `selectedQuantityValue` the count. The order history card gives the Store's name ("Wegmans +8" when it shows eight more pictures) and its item count, which must match the lines read.

**Error codes** stop the whole job and become one spoken sentence (FR-0.40): `signed_out` and `needs_human` ("Instacart needs you in Chrome on the laptop."), `wrong_address`, `page_changed` (the page didn't have what the code looks for), `no_page` (didn't load in 30 s); and from Kiki's side `no_answer` and `no_chrome` ("I can't reach Instacart in Chrome. Is the Kiki extension on?"). Per-line problems (`unavailable`, `sold_out`, `not_found`, `not_added`, `more_than_nine`) only fail that line.

**The flows** (`ordering.py`):

- `read_new_orders`: asks for the Orders Kiki doesn't know, keeps the delivered ones to `KIKI_ADDRESS` (the first time, the seven newest), checks each line (a known status, a numeric product id, a name, a count; as many lines as the order history says) and saves it with `save_order`. An Order that fails a check isn't saved and is reported in `unreadable_orders` with why, for example `unknown status 'refunded'`: Kiki doesn't guess what a new word means.
- `learn_product_preferences` ("analyze my order", FR-0.36): reads new Orders, then gives every Item without a Product one. **One Claude request** (`match_products`, ADR 0035) gets the Items' names and the placed Products' names and says which Products are which Item; `preferred_product` then picks, in code, the one in the most Orders, the most recent on a tie (FR-0.37). It never changes an Item that has a Product.
- `fill_cart` ("order the groceries", FR-0.39): reads new Orders, matches only the Needed Items without a Product, then sends every Needed Item to the extension at its quantity. An Item still without a Product gets a search result for this Cart only, one tagged "Buy it again" first; it's learned once it shows up in a delivered Order. If the matching request fails, the fill goes on with top results (FR-0.40).
- `choose_product` ("use Diamond walnuts for walnuts", FR-0.38): a placed Product whose name has every word said, else a search result ("Buy it again" first).

**Replies** are Kiki's own, at most two sentences, because the model can't know the result when it writes `reply`: "Your cart is ready with twelve items. Blueberries failed, and two were top matches, details on the screen." The History chips have the details: every top match and failure, every Product matched, every Order that couldn't be read.

**Timing** (measured 2026-10-23 on the owner's account, from typing the command to the reply): a search 3.2 to 3.5 s; "analyze my order" reading five Orders and matching 18 Items 19 to 20 s (5 s with no new Orders); "use ... for walnuts" 4.5 to 5.8 s when it searches; "order the groceries" with 17 Items 54 to 60 s, about 3.3 s an Item. The turn holds the turn lock all that time; the state line shows "Filling cart, 4 of 17".

**Chrome's state doesn't matter** (measured 2026-10-23, 17 Items): with Chrome open, the fill took 54 to 60 s; with every window closed and Chrome still running in the background, `chrome.exe` opened a window, filled the Cart in 73 s and the window closed with its tab; with Chrome fully stopped, it started signed in and took 68 s. With another tab in front of Kiki's, Chrome slows the background tab and the fill took 90 s, all Items in. Kiki never moves the mouse or types: the extension's clicks are `element.click()` inside the page. An old `#kiki` tab that Chrome restores at start-up finds no job; the extension closes it without an error. A Product page that shows no buttons within 15 s is loaded once more before it counts as sold out, unless it says "out of stock", "sold out" or "unavailable" (one slow page took longer than that in testing).

**The Cart filling, live on the Tab5** (v0.19, FR-0.42, [ADR 0037](docs/adr/0037-show-the-cart-filling-on-the-tab5-with-chromes-screencast.md)). For a `fill_cart` job only, the extension attaches `chrome.debugger` to Kiki's tab and starts DevTools' `Page.startScreencast` (JPEG, quality 60, scaled by Chrome to fit 720×360). It acks every frame and posts one at a time to `POST /instacart/frame`, skipping those that come while a post is on its way. Chrome shows "Kiki for Instacart started debugging this browser" until the tab closes, which detaches it. A failed attach (DevTools already open on that tab) leaves the fill running, unseen. Chrome sends frames only when the tab repaints, so a tab behind another one, or a minimised window, sends none and the Tab5 keeps the last. The Tab5 side is `live.ino` (above). Measured on the owner's Chrome and the Tab5 (2026-10-23, three fills of 4 Items): the first frame reached Kiki 5–8 s after "order the groceries"; frames were 540×360 (the window's 3:2 shape), about 11 KB; the Tab5 showed them in the orb's slot with true colours and went back to the orb when the fill ended, its loop's slowest step still 4 ms and the orb at 40 fps. Touches during a fill, checked on the Tab5 the same day with `serial.ps1` and `shot.ps1`: taps on a row, History, the text box and Reset twice, swipes on the List, a press already down when it starts, and starting it with the item sheet, a rename, the keyboard (typed text kept) or History open all leave nothing open, and the orb shows no frame until the fill's end. With taps and swipes during a real fill, frames kept coming (720×338, 17 ms to decode and show; the loop's slowest step 18 ms). Found on the way: LVGL's top layer scrolled, so a swipe on anything there pulled the parked item sheet into view; it no longer scrolls.

**The matching request runs on its own thread.** It's made from inside `update_list`, during the command's own agent run, where Pydantic AI refuses a nested `run_sync` (it could deadlock); a fresh thread is outside that run. Found end to end: the unit tests used a fake matcher. Any other error in an ordering step becomes "Something went wrong with Instacart, please try again." rather than a turn that never ends.

## Matching names

`normalize()` in `tools.py` maps singular and plural to one key with suffix rules: lowercase, collapse spaces, drop a trailing `s` (not `ss`, `us`, `is`), then `ie` to `y` and drop the `e` of `oe`, `che`, `she`, `xe`, `sse`. The key isn't always a real word ("cookie" becomes "cooky"); it only has to match both forms. Irregular plurals ("loaves") aren't handled.

## Data model

`items` holds both the Item and its state for the next Order ([ADR 0026](docs/adr/0026-one-item-table-holds-the-next-order-state.md), terms in [CONTEXT.md](CONTEXT.md)). Nothing is ever deleted. Since v0.17 three more tables hold the Store's side: `products`, `orders` and `order_lines` ([ADR 0035](docs/adr/0035-learn-each-items-product-from-what-was-placed.md)).

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
| `product_id` | integer, nullable, → `products.id` | The Product the Cart gets for this Item; empty until one is learned or chosen |

`products`: `id` (the Store's own id, so the page is `/store/<store>/products/<id>`), `name`.

`orders`: `id` (the order history's id), `delivered_at`. Only delivered Orders from `KIKI_STORE` to `KIKI_ADDRESS`.

`order_lines`: `order_id`, `product_id` (what was **placed**, never the substitute), `quantity`, `status` (`found`, `substituted`, `missing`); one per Product per Order.

**The List** is every Frequent item plus the Needed Occasional ones, Needed first (`read_list`). A Not needed Occasional item is hidden but still known, so "add butter" brings it back at its usual quantity.

**Files from before v0.12:** `db.connect` renames an `items` table without `buying_pattern` to `items_before_v0_12` and starts an empty List. The old rows are kept, not migrated. A v0.12 to v0.16 file keeps its List: `db.connect` adds `items.product_id` and the three new tables.

## Tools

All tools are plain functions taking and returning JSON-compatible values ([ADR 0008](docs/adr/0008-tools-are-plain-functions.md)). The model never calls them directly; it calls `update_list`, which calls them. Names say what they change, with `_for_item` when they change one Item ([ADR 0036](docs/adr/0036-tool-names-say-what-they-change.md)).

| Tool | Input | Output | Notes |
|---|---|---|---|
| `add_items` | `items: [{name, quantity?}]` | `{added: [...], already_present: [...]}` | A new name is Occasional and Needed. A Not needed item becomes Needed at the quantity said, else its usual. A Needed item is left alone (FR-0.2, FR-0.20) |
| `set_quantity` | `name, quantity` | `{name, quantity}` or `{not_found: name}` | The next Order's quantity, for explicit changes like "make it three"; also makes the item Needed (FR-0.3, FR-0.22). The model computes the new number from the list snapshot |
| `set_usual_quantity` | `name, quantity` | `{name, usual_quantity}` or `{not_found: name}` | "We usually get three tomatoes": usual and next quantity (FR-0.22) |
| `set_buying_pattern` | `name, buying_pattern` | `{name, buying_pattern}` or `{not_found: name}` | Frequent or Occasional (FR-0.23) |
| `rename_item` | `name, new_name` | `{name, new_name}`, `{not_found: name}` or `{error}` | Same item, new name; an error if the new name is another item (FR-0.24) |
| `remove_items` | `names: [string]` | `{removed: [...], not_found: [...]}` | Makes items Not needed, whatever the quantity; already Not needed counts as not found (FR-0.21) |
| `read_list` | none | `{items: [{name, quantity, buying_pattern, status, product_name}]}` | The List. Builds the snapshot; not offered to the model, since the snapshot already answers questions (FR-0.19) |
| `clear_all_items` | none | `{removed: [{name, quantity}]}` | Every item Not needed, no confirmation; returns the ones that were Needed (FR-0.26, [ADR 0012](docs/adr/0012-clear-list-without-confirmation.md)). Called `clear_list` before v0.17; older logs still say so |
| `reset_list` | none | `{needed: [{name, quantity}]}` | Starts the List over: Frequent items Needed at their usual quantity, Occasional ones Not needed (FR-0.35). Only the Reset button calls it, never the model |
| `set_product_for_item` | `name, product_id, product_name` | `{name, product_name}` or `{not_found: name}` | The Product the Cart gets for this Item (FR-0.38) |
| `forget_product_for_item` | `name` | `{name}` or `{not_found: name}` | The Item has no Product again (FR-0.34, FR-0.38) |
| `save_order` | `{id, delivered_at, lines: [{product_id, product_name, quantity, status}]}` | `{order_id, lines}` | One delivered Order; a line's Product is what was placed (FR-0.36) |
| `known_order_ids`, `items_without_product`, `placed_products`, `cart_lines` | | lists | What the ordering flows read |
| `read_all_items` | none | `{items: [{..., on_list}]}` | Every Item, the List first then the rest by name, for the screens' events (FR-0.41). The model's snapshot still uses `read_list` |
| `preferred_product` | `product_ids` | `{id, name, orders, last_ordered}` or null | Of these Products, the one in the most Orders; a tie goes to the most recent (FR-0.37) |

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

- `source` is `text`, `voice` or `button` (the Reset button, v0.17). `stt` and `tts` latencies are `null` in v0.1. `llm` is the whole agent run (model requests plus tool time), so in v0.1 it equals `total`.
- `error` is null, or a short string when the turn failed (for example, no internet).

**`state`**, live only and not logged:

```json
{"type": "state", "value": "idle | listening | thinking | speaking | error"}
```

| Value | Published by | When |
|---|---|---|
| `listening` | `WakeGate` | wake word heard; reply finished (the follow-up window) |
| `thinking` | `WakeGate`, `ui.send_command` | end of a command, before the agent answers |
| `idle` | `WakeGate`, `Brain`, `ui.send_command` | nothing said after the wake word or in the follow-up window; a command with no words (no transcript within `NO_WORDS_SECS`, 3 s); a follow-up that wasn't a command; reply finished |
| `speaking` | `Brain` | first reply audio plays (`BotStartedSpeakingFrame`) |
| `error` | `Brain`, `ui.send_command` | the turn had an `error` (shown until the next state) |

**`list`**, live only: every Item Kiki knows after every turn and every list click, the List first, `{"type": "list", "items": [{"name", "quantity", "buying_pattern", "status", "product_name", "on_list"}]}`. `on_list` false is an Occasional Item that isn't Needed: the screens show it under "Not on the list" (v0.18, FR-0.41). The `snapshot`'s `items` are the same.

**`progress`**, live only, while the Cart fills: `{"type": "progress", "text": "Filling cart, 4 of 12"}`. Both screens show it in the state line until the next `state`.

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
| `KIKI_WAKE_THRESHOLD` | `0.5` | openWakeWord score (0–1) that counts as "hey jarvis". Raise if it wakes by itself, lower if it misses you. On the Tab5's mic (2026-10-22) real wakes scored 0.73–0.90 and talk and TV at most 0.46; 0.4, tuned on the laptop mic, woke about six times in an evening. The terminal logs every wake (`wake word heard (score 0.99)`) and every near-miss (`almost heard the wake word (score 0.42, needs 0.50)`), so you can see how close a missed "hey jarvis" came |
| `KIKI_LISTEN_TIMEOUT_SECS` | `6` | How long the gate stays open after the wake word if nobody speaks |
| `KIKI_FOLLOW_UP_SECS` | `5` | How long Kiki listens after each reply for another command without the wake word |
| `KIKI_PAUSE_SECS` | `0.2` | A pause this long makes Smart Turn check whether the sentence sounds finished |
| `KIKI_END_GRACE_SECS` | `0.4` | After a pause sounds finished, how long to wait for more words before closing (list commas) |
| `KIKI_MAX_PAUSE_SECS` | `3` | Silence that ends a command even if it sounded unfinished |
| `KIKI_WHISPER_MODEL` | `base.en` | faster-whisper model name, printed at start-up. `small.en` is more robust but adds about 1.1 s. `distil-small.en` is no faster than `small.en` on short commands (Whisper's encoder always reads 30 s) and no more accurate than `base.en`: 1.53 s vs 0.56 s per command on battery (`python -m kiki.stt_bench`, 2026-10-22) |
| `KIKI_WHISPER_THREADS` | `8` | CPU threads for Whisper, one per core of this laptop. faster-whisper's own default is 4, about 0.15 s slower; more threads than cores is slower again |
| `KIKI_CHIME_VOLUME` | `0.45` | Peak level of the listening chime, 0 to 1 (about -7 dBFS by default) |
| `KIKI_PIPER_VOICE` | `en_US-lessac-medium` | Piper voice; downloaded on first run to `~/.cache/pipecat/piper` |
| `KIKI_UI_PORT` | `8765` | UI port |
| `KIKI_STORE` | `wegmans` | The Store's Instacart name in its URLs; only its Orders are read and only its Cart is filled (v0.17) |
| `KIKI_ADDRESS` | `30 River Court` | Only Orders delivered here are read, and the Cart is filled only while Instacart is set to it |
| `KIKI_UI_HOST` | `127.0.0.1` | Address the UI binds to. `0.0.0.0` opens it to the home network for a Tab5 program that follows `/events` itself (NFR-0.7); no password yet |
| `KIKI_MIC` | laptop | `tab5`: listen through the Tab5's mic instead of the laptop's (FR-0.29) |
| `KIKI_MIC_PORT` | `8768` | UDP port the Tab5's mic sends to |
| `KIKI_SPEAKER` | laptop | `tab5`: play the chime and replies on the Tab5 instead of the laptop (FR-0.30) |
| `KIKI_SPEAKER_PORT` | `8769` | TCP port the Tab5's speaker connects to |
| `KIKI_SCREEN_PORT` | `8767` | TCP port the Tab5's screen connects to (`python -m kiki.screen`) |
| `KIKI_SCREEN_QUALITY` | `70` | JPEG quality of the frames sent to the Tab5 |
| `KIKI_CHROME` | `C:\Program Files\Google\Chrome\Application\chrome.exe` | The Chrome that renders the page for the Tab5, and the owner's Chrome that Kiki opens its Instacart tabs in (v0.17) |

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

v0.17 adds none either: the Kiki for Instacart extension (`browser/instacart`) is plain JavaScript that the owner loads into their own Chrome, and Kiki starts Chrome with `subprocess`. v0.19 adds none: the screencast is Chrome's own, and the Tab5's JPEG decoder is ESP-IDF's, already in the board package.

| Dependency (v0.14) | Why | Since |
|---|---|---|
| `websockets` (already installed with Pipecat, now used directly) | `screen.py` talks to Chrome over the DevTools protocol, a WebSocket ([ADR 0028](docs/adr/0028-stream-the-real-ui-page-to-the-tab5.md)) | v0.14 |
| Google Chrome (installed on the laptop, not a Python package) | Renders the page for the Tab5 | v0.14 |
| `arduino-cli` 1.5.1 (installed with winget) | Builds and flashes the Tab5 program ([ADR 0032](docs/adr/0032-device-code-lives-in-this-repo.md)) | v0.14 |
| Board package `m5stack:esp32` 3.3.10 | The ESP32-P4 tool chain and the `M5Tab5` board, with ESP-IDF's JPEG decoder | v0.14 |
| M5Unified 0.2.27, M5GFX 0.2.34 (Arduino libraries) | The Tab5's display, touch, mic, speaker and power | v0.14 |
| LVGL 9.6.0 (Arduino library, MIT) | The native UI's widgets, fonts and partial redraws ([ADR 0033](docs/adr/0033-draw-the-ui-natively-on-the-tab5.md)) | v0.15 |
| ArduinoJson 7.4.3 (Arduino library, MIT) | Parses Kiki's events on the Tab5 | v0.15 |
| Inter (SIL OFL 1.1, from fontsource), converted with `lv_font_conv` 1.5.3 (build time only) | The native UI's text, as in DESIGN.md | v0.15 |

## Testing

- `test_tools.py`, `test_events.py`, `test_agent.py`: deterministic, no network. Always run. `test_agent.py` scripts the model with Pydantic AI's `FunctionModel`, so it checks what the model is sent, retries and guards without an API call.
- `test_voice.py`: the gate tests use a fake detector and are instant. Real-model tests put `RealTimeMic` first, which releases audio at real-time pace: Smart Turn and VAD keep wall-clock time, and audio pushed all at once hid the list-comma problem. Waits are streamed silence, never `SleepFrame`, because a real mic keeps sending silence and the 3 s fallback counts it. Tests marked `voice` run the real wake word, Silero, Whisper and Piper on speech synthesized by Piper ([ADR 0017](docs/adr/0017-test-voice-with-synthesized-speech.md)); `test_scenario_by_voice` (also marked `scenario`) speaks the seven v0.2 scenarios and v0.12 scenarios 13, 16 and 22 to the real agent. First run downloads the Whisper and Piper models.
- `test_latency.py`: the log report. `test_voice.py::test_nfr_0_3_*` (marked `voice` and `scenario`) speaks twenty commands through the full chain to the real agent and requires a median `total` of 2 s or less.
- `test_ui.py`: real HTTP against a server on a random port with a scripted model: the page, the orb script served locally, the live event sequence for a typed command (`thinking`, `turn`, `list`, `idle`), past runs in the snapshot, list clicks and item edits (`POST /item`: needed, quantity, new name, refusals), localhost binding, and the Host, content-type and length checks; the extension's job, answer and frames over HTTP (only the running job's newest JPEG reaches the Tab5), and its manifest's permissions.
- `test_tab5.py`: the laptop's side of each Tab5 link over real sockets, with plain sockets standing in for the Tab5: mic packets become audio frames in order (FR-0.29); a second of speaker audio arrives whole, over about 0.85 s (FR-0.30); the screen sends the newest frame after each `shown` and turns touch lines into touch events (FR-0.31); the keyboard script is added after `Page.enable` and before the page loads (FR-0.32). `test_nfr_0_8_*` (marked `voice`) sends synthesized speech as the Tab5's UDP packets through the real wake word and Whisper and checks the model gets only text. The Tab5 program itself is checked by hand.
- `test_scenarios.py`: sends each ROADMAP scenario to the real model and asserts on tool calls and final list state, not on exact wording. A full run is 23 short Haiku turns, about a cent. Needs `ANTHROPIC_API_KEY`; skipped automatically without it, or deselect with `-m "not scenario"`.
