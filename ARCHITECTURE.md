# Architecture

How Kiki works right now. Update this file in the same commit as any code change that alters it. For *why* each choice was made, see [docs/adr/](docs/adr/README.md).

## Overview

```
v0.1 (terminal)
  keyboard ──> cli.py ──> agent.py (Pydantic AI) ──> model API ──> tools.py ──> db.py ──> kiki.db
                  ^            │
                  └── reply ───┤
                               └──> events.py ──> logs/turns.jsonl

v0.2 (voice, adds voice.py around the same agent)
  mic ──> openWakeWord ──> VAD / turn detection ──> faster-whisper ──> agent.py ──> Piper ──> speaker
          (local gate)     (Pipecat: Silero)        (local STT)        (as above)   (local TTS)

v0.4 (UI)
  events.py ──> local WebSocket ──> browser on localhost (orb, list, history)
```

| Layer | Choice | ADR |
|---|---|---|
| Orchestration | Pipecat | [0002](docs/adr/0002-use-pipecat-for-voice-orchestration.md) |
| Wake word | openWakeWord, built-in "hey jarvis", runs before STT | [0003](docs/adr/0003-gate-audio-with-local-wake-word.md) |
| Audio in/out (v0.2) | Pipecat `LocalAudioTransport`, Python owns mic and speaker | [0011](docs/adr/0011-python-owns-the-mic-in-v0.md) |
| STT | faster-whisper `small`, English | [0004](docs/adr/0004-run-stt-and-tts-locally.md) |
| Agent framework | Pydantic AI: tool loop, argument validation, retries, output guard, usage limit | [0015](docs/adr/0015-use-pydantic-ai-for-the-agent.md) |
| Brain | Any Pydantic AI model string, default `anthropic:claude-haiku-5-5` | [0005](docs/adr/0005-use-claude-haiku-by-default.md), [0015](docs/adr/0015-use-pydantic-ai-for-the-agent.md) |
| TTS | Piper (Kokoro if Piper sounds too robotic) | [0004](docs/adr/0004-run-stt-and-tts-locally.md) |
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
  voice.py    Pipecat pipeline (v0.2)
tests/
  test_tools.py       tools.py against a temp SQLite file
  test_events.py      turn log format
  test_agent.py       agent loop against Pydantic AI's FunctionModel / TestModel
  test_scenarios.py   ROADMAP scenarios against the real Claude API (marked `scenario`)
web/                  UI (v0.4)
```

`src/` layout is uv's default for a package (`uv init --lib`).

## Request flow (one turn)

1. A command arrives as text (typed in v0.1, transcribed in v0.2).
2. `run_turn` snapshots the list once, then calls `agent.run_sync` with only the command. The model sees the static instructions, the snapshot and the command. No previous turns ([ADR 0009](docs/adr/0009-single-turn-commands.md)).
3. The model calls tools. Each Pydantic AI tool in `agent.py` is a thin wrapper that calls the plain function in `tools.py`, records the call in `Deps.tool_calls` and returns the result.
4. `run_turn` returns a `turn` event. `events.py` appends it to the log. The caller prints or speaks `said`.

**Why the snapshot is taken once:** Pydantic AI re-renders instructions on every model request inside a run. A live list read would show "bread x2" after the first `set_quantity`, and the model would bump "add another bread" again (found by scenario 3).

### Guards (all Pydantic AI built-ins)

| Guard | What happens |
|---|---|
| Argument validation | Tool parameters are typed (`Item.quantity >= 1`, `set_quantity.quantity >= 1`). Invalid arguments never reach `tools.py`; the model gets a retry prompt. |
| Tool errors | A tool result with an `error` key is raised as `ModelRetry`, so the model sees the message and can correct itself. The call is still logged. |
| Output guard | `spoken_style` output validator rejects markdown, bullets, underscores and digits with a retry (FR-0.10). Empty replies are retried by Pydantic AI itself. |
| Retries | `retries=2` per tool and for the output. |
| Usage limit | `UsageLimits(request_limit=6)` stops a runaway tool loop. |
| Model settings | `thinking="low"` (unified setting, maps to each provider's effort), `max_tokens=4096`. |

### Failure replies

| Failure | `said` | `error` |
|---|---|---|
| Retries exhausted, no speakable reply | "Sorry, I didn't catch that." | `UnexpectedModelBehavior: ...` |
| No internet (`ModelAPIError`) | "I can't reach the internet right now." | `connection error` |
| API error (`ModelHTTPError`) | "Something went wrong, please try again." | `API error <status>` |
| Usage limit or other run error | "Something went wrong, please try again." | exception name and message |

Tools that ran before a failure stay in `tool_calls`, so the log still shows them (for example, a `clear_list` that ran before the connection dropped).

**SQLite and threads:** Pydantic AI runs sync tools in worker threads, so `db.connect` uses `check_same_thread=False`. Calls within a turn are sequential.

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

All tools are plain functions taking and returning JSON-compatible values ([ADR 0008](docs/adr/0008-tools-are-plain-functions.md)).

| Tool | Input | Output | Notes |
|---|---|---|---|
| `add_items` | `items: [{name, quantity?}]` | `{added: [...], already_present: [...]}` | Never changes the quantity of an existing item (FR-0.2) |
| `set_quantity` | `name, quantity` | `{name, quantity}` or `{not_found: name}` | For explicit changes like "add another milk" or "make it three" (FR-0.3). The model computes the new number from the list snapshot |
| `remove_items` | `names: [string]` | `{removed: [...], not_found: [...]}` | Deletes the whole item regardless of quantity (FR-0.5) |
| `read_list` | none | `{items: [{name, quantity}]}` | |
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

**`state`**, live only and not logged (v0.2 onward, consumed by the UI in v0.4):

```json
{"type": "state", "value": "idle | listening | thinking | speaking | muted | error"}
```

Adding a field is fine. Renaming or removing one needs an ADR.

## Instructions

The source of truth is `INSTRUCTIONS` in `agent.py`, plus a dynamic line "Current list at the start of this request: ...". In short: speak in one or two short sentences with numbers as words; use tools for every change; fix obvious speech-to-text slips; never change an existing item unless the quantity change is explicit; remove means delete completely; read every item when asked; after clearing say only the count; when unsure reply exactly "Sorry, I didn't catch that." and call no tools.

## Configuration

Environment variables only. A local `.env` is fine (never committed) and is loaded with `uv run --env-file .env ...`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none, required for the default model | Claude API key. Another provider needs its own key (e.g. `OPENAI_API_KEY`) |
| `KIKI_MODEL` | `anthropic:claude-haiku-5-5` | Pydantic AI model string, `provider:model`. Swap with e.g. `openai:<model>`; `test` runs Pydantic AI's offline TestModel |
| `KIKI_DB` | `kiki.db` | SQLite file path |
| `KIKI_LOG` | `logs/turns.jsonl` | Turn log path |

## Dependencies

Approved. Anything else needs the owner's yes and an ADR.

| Dependency | Why | Since |
|---|---|---|
| `pydantic-ai-slim[anthropic]` | Agent framework and Anthropic provider ([ADR 0015](docs/adr/0015-use-pydantic-ai-for-the-agent.md)). Another provider is a new extra, e.g. `[openai]` | v0.1 |
| `sqlite3` (stdlib) | State | v0.1 |
| `pytest` (dev) | Tests | v0.1 |
| `ruff` (via `uvx`, not installed) | Lint and format | v0.1 |
| `pipecat-ai` and its extras for local audio, Silero, Whisper, Piper | Voice pipeline | v0.2 |
| `openwakeword` | Wake word | v0.2 |
| `faster-whisper` | STT | v0.2 |
| Piper (or Kokoro) | TTS | v0.2 |

UI dependencies are decided with the v0.4 design.

## Testing

- `test_tools.py`, `test_events.py`, `test_agent.py`: deterministic, no network. Always run. `test_agent.py` scripts the model with Pydantic AI's `FunctionModel`, so it checks what the model is sent, retries and guards without an API call.
- `test_scenarios.py`: sends each ROADMAP scenario to the real model and asserts on tool calls and final list state, not on exact wording. A full run is 11 short Haiku turns, well under a cent. Needs `ANTHROPIC_API_KEY`; skipped automatically without it, or deselect with `-m "not scenario"`.
