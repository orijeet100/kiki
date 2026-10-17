# Architecture

How Kiki works right now. Update this file in the same commit as any code change that alters it. For *why* each choice was made, see [docs/adr/](docs/adr/README.md).

## Overview

```
v0.1 (terminal)
  keyboard ──> cli.py ──> agent.py ──> Claude API (tools) ──> tools.py ──> db.py ──> kiki.db
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
| Brain | Claude via API, default `claude-haiku-5-5` | [0005](docs/adr/0005-use-claude-haiku-by-default.md) |
| TTS | Piper (Kokoro if Piper sounds too robotic) | [0004](docs/adr/0004-run-stt-and-tts-locally.md) |
| State | SQLite, one file | [0006](docs/adr/0006-store-state-in-sqlite.md) |
| Host | The laptop, permanently | [0007](docs/adr/0007-laptop-is-the-permanent-host.md) |

## Code layout

```
kiki/
  db.py       SQLite connection and schema
  tools.py    the tool functions (plain Python, no voice or Claude knowledge)
  agent.py    one command in, one turn out: builds the prompt, runs the Claude tool loop
  events.py   turn/state event shapes, appends turns to the log
  cli.py      terminal loop (v0.1)
  voice.py    Pipecat pipeline (v0.2)
tests/
  test_tools.py       deterministic tests of tools.py, no API calls
  test_scenarios.py   ROADMAP scenarios against the real Claude API
web/                  UI (v0.4)
```

## Request flow (one turn)

1. A command arrives as text (typed in v0.1, transcribed in v0.2).
2. `agent.py` builds a fresh request: system prompt + current list snapshot (from `read_list`) + the command. No previous turns ([ADR 0009](docs/adr/0009-single-turn-commands.md)).
3. Claude calls tools. `agent.py` runs them against `tools.py` and returns results until Claude produces the final reply.
4. `agent.py` returns a `turn` event. `events.py` appends it to the log. The caller prints or speaks `said`.

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
| `set_quantity` | `name, quantity` | `{name, quantity}` or `{not_found: name}` | For explicit changes like "add another milk" or "make it three" (FR-0.3). Claude computes the new number from the list snapshot |
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
     "args": {"items": [{"name": "bread"}, {"name": "milk", "quantity": 2}]},
     "result": {"added": ["bread", "milk"], "already_present": []}}
  ],
  "said": "Added bread and two milks.",
  "model": "claude-haiku-5-5",
  "latency_ms": {"stt": null, "llm": 900, "tts": null, "total": 950},
  "error": null
}
```

- `source` is `text` or `voice`. `stt` and `tts` latencies are `null` in v0.1.
- `error` is null, or a short string when the turn failed (for example, no internet).

**`state`**, live only and not logged (v0.2 onward, consumed by the UI in v0.4):

```json
{"type": "state", "value": "idle | listening | thinking | speaking | muted | error"}
```

Adding a field is fine. Renaming or removing one needs an ADR.

## System prompt (starting point)

> You manage a household grocery list by voice. Replies are spoken aloud: one or two short sentences, no markdown, bullets or emojis, numbers written as words. Use the tools for every change. Each request is independent; you only know the current list shown below. If an item is already on the list, say so and don't change it unless the user explicitly asks for a different quantity. If you can't tell what the user wants, reply exactly "Sorry, I didn't catch that." and call no tools.
>
> Current list: {list}

## Configuration

Environment variables only (a local `.env` is fine, never committed):

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | none, required | Claude API key |
| `KIKI_MODEL` | `claude-haiku-5-5` | Model name |
| `KIKI_DB` | `kiki.db` | SQLite file path |
| `KIKI_LOG` | `logs/turns.jsonl` | Turn log path |

## Dependencies

Approved. Anything else needs the owner's yes and an ADR.

| Dependency | Why | Since |
|---|---|---|
| `anthropic` | Claude API | v0.1 |
| `sqlite3` (stdlib) | State | v0.1 |
| `pytest` (dev) | Tests | v0.1 |
| `ruff` (via `uvx`, not installed) | Lint and format | v0.1 |
| `pipecat-ai` and its extras for local audio, Silero, Whisper, Piper | Voice pipeline | v0.2 |
| `openwakeword` | Wake word | v0.2 |
| `faster-whisper` | STT | v0.2 |
| Piper (or Kokoro) | TTS | v0.2 |

UI dependencies are decided with the v0.4 design.

## Testing

- `tests/test_tools.py`: deterministic, runs against a temporary SQLite file, no network. Always run.
- `tests/test_scenarios.py`: sends each ROADMAP scenario to the real Claude API and asserts on tool calls and final list state, not on exact wording. Costs a little money, needs `ANTHROPIC_API_KEY`, and is marked `scenario` so it can be skipped (`uv run pytest -m "not scenario"`).
