# Design (UI)

> Owner's document. v0.4 shipped a **first cut** so Kiki could be watched working; every choice below is open to change. Edit this file, then the UI follows it. This file covers what the UI shows and does; colors, fonts and components are in [DESIGN.md](../DESIGN.md).

## What it's for

Watching Kiki work: what it heard, what it did, what it said, and how the list changed, without reading the terminal.

## Already decided

- Runs in a browser on the laptop, localhost only (NFR-0.6).
- Driven by Kiki's own `state`, `turn` and `list` events ([ARCHITECTURE.md](../ARCHITECTURE.md#events)).
- Three areas: an orb showing the assistant state, the grocery list, and a history of runs.
- Inspiration: the ElevenLabs UI orb.

## v0.4 first cut (open to change)

| Topic | First cut |
|---|---|
| Layout | Three panels side by side (assistant, list, runs); stacked on narrow screens |
| Sounds | Soft glass chimes (owner's pick of glass, marimba and bell): rising fifth when Kiki starts listening, at a peak of 0.45 (`KIKI_CHIME_VOLUME`); no sound when it stops (the closing chime was removed) |
| Orb | CSS conic gradient (orange, yellow, pink). Idle: dim, slow breathing. Listening: bright glow, fast breathing. Thinking: fast spin, slightly smaller. Speaking: quick pulse with a pink glow. Error: red. No motion under "reduce motion" |
| Turn card | Time and source (voice/text), total latency; Heard, Did (chips such as "added bread, milk ×2", "already there: bread", "removed eggs", "milk → 3"), Said. Under Details: per-stage latency, model, raw tool calls |
| List panel | Read-only. Rows that are new or changed flash yellow for 1.5 s. Count in the heading |
| History | Last 50 runs from the log on load, newest first; live runs added on top |
| Text box | Under the orb, so the UI works without a microphone |
| Theme | Follows the system's light or dark setting |
| Stack | One HTML file, no dependencies ([ADR 0020](adr/0020-ui-over-server-sent-events.md)) |

## Still open

- **Audio-reactive orb:** the first cut doesn't follow voice volume. Needs volume events from the voice loop.
- **The real ElevenLabs orb:** needs React, three.js and a build step (new ADR).
- **Removed items:** they vanish from the list; the run card shows what was removed. A brief strike-through could show it in the list too.
- **Editable list:** ticking items off on screen would be a second way to change state and needs its own tests.
- **The M5 screen:** a much smaller layout for the fridge device.

## Sketches

(add images or links here)
