# 0024. The orb is the Speaking Orb web component, vendored as one file

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.13, FR-0.16, FR-0.17, NFR-0.6. Supersedes the orb part of 0020 (the CSS conic-gradient orb).

## Context
The owner asked for the Speaking Orb from Ship Notes (https://aqualang89.github.io/shipnotes-components/components/speaking-orb/) in place of the v0.4 CSS orb. ADR 0020 kept the UI to one HTML file with no dependencies, and said the real ElevenLabs orb would need a build step. The Speaking Orb is a different case: one MIT-licensed JavaScript file, a custom element (`<speaking-orb>`), no libraries, no network, WebGL with a Canvas 2D fallback, and it freezes under reduced motion. It has the shapes Kiki needs (listening, thinking, speaking, done) and live captions built from particles.

## Options considered
- Keep the CSS orb: no change, but it's the look the owner wants replaced.
- Load the script from the Ship Notes site: no file in the repo, but the page would fetch code from the internet on every load, and stop working offline.
- Inline the script into `ui.html`: still one file, but 22 KB of someone else's code mixed into ours, and FR-0.16's color check would have to skip it.
- Vendor `speaking-orb.js` next to `ui.html` and serve it at `/speaking-orb.js`: one more static route, the license travels with the file, upgrades are a file swap.

## Decision
Vendor it as `src/kiki/speaking-orb.js`, served by `ui.py`, with the MIT notice in the file. Kiki's only change to it: in `connectedCallback` it reads its five state colors from `--orb-<state>` custom properties (hex). `ui.html` sets those properties to DESIGN.md tokens, used exactly, so the palette still lives in one `:root`.

Kiki's `state` maps to the orb as: idle → listening shape, still, smaller and dimmed; listening → listening shape at full size, rippling, thinking → thinking, speaking → speaking, error → listening shape, grayscale. Each turn's reply goes to `say()` with estimated word timings, which shows captions without the browser speaking (Piper already did). A turn without an error ends on the `done` check mark for 1.8 s.

## Consequences
+ The orb reacts to speech (syllable rings, a swelling sphere) and shows what Kiki said as captions.
+ Still nothing to install or build; nothing fetched from the network (FR-0.17 checks it).
- A vendored file to keep: an upstream fix means copying the new file and re-applying the one color line.
- The swell is estimated from syllables, not Piper's real audio, because audio plays in Python, not the browser. A real envelope needs volume events from the voice loop (still open in docs/ui.md).
