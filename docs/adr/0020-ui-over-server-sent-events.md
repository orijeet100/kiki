# 0020. The UI is one HTML page over Server-Sent Events, standard library only

- Status: Accepted; orb superseded by 0024
- Date: 2026-10-17
- Related: FR-0.13, NFR-0.6. Builds on 0010 (own events), 0011 (which expected "a local WebSocket").

## Context
v0.4 needs a local page that shows the assistant state, the list and the runs live, driven by Kiki's own events. Data only flows server → browser, except for typed commands.

## Options considered
- React + the ElevenLabs Orb component (three.js, Tailwind, shadcn): the exact orb look, but a Node build and about eight npm dependencies.
- WebSocket server: two-way, but needs a dependency (`websockets` or FastAPI) for a one-way stream.
- `http.server` + Server-Sent Events + one HTML file with a CSS orb: no dependencies, no build; the browser's `EventSource` reconnects by itself; typed commands are a plain `POST`.

## Decision
Standard library `ThreadingHTTPServer` on 127.0.0.1, `GET /events` as Server-Sent Events, `POST /command` for the text box, and `ui.html` with a CSS conic-gradient orb.

## Consequences
+ Nothing to install or build; the UI ships inside the package.
+ The same events feed the log, the terminal and the page.
- The orb is a CSS look-alike and doesn't react to audio volume. If DESIGN.md asks for the real ElevenLabs orb, that's a new ADR and a build step.
