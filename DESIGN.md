# Design (UI, v0.4)

> Owner to fill in. v0.4 starts only once this is written. Prompts below are a starting point; delete what you don't need.

## What it's for

Watching Kiki work: what it heard, what it did, what it said, and how the list changed, without reading the terminal.

## Already decided

- Runs in a browser on the laptop, localhost only (NFR-0.6).
- Driven by Kiki's own `turn` and `state` events ([ARCHITECTURE.md](ARCHITECTURE.md#events)).
- Three areas: an orb showing the assistant state, the grocery list, and a history of turns.
- Inspiration: the ElevenLabs UI orb.

## To decide

- **Layout:** sketch where the orb, list and history sit.
- **Orb states:** how idle, listening, thinking, speaking, muted and error each look.
- **Turn card:** what each history entry shows (heard, tool calls, reply, latency) and what is collapsed by default.
- **List panel:** how a just-changed item is highlighted. Read-only or editable?
- **History:** how many past turns load from the log when the page opens.
- **Stack:** React + the ElevenLabs Orb component, or a single HTML file with a hand-made orb (new dependencies need an ADR).

## Sketches

(add images or links here)
