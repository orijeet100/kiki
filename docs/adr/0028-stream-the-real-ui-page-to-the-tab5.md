# 0028. The Tab5 shows the real UI page, rendered by a headless Chrome on the laptop and streamed as JPEG frames

- Status: Accepted
- Date: 2026-10-21
- Related: FR-0.31, FR-0.32, FR-0.13, ADR 0027

## Context
The owner wants the same UI on the fridge as in the browser: the Speaking Orb, the list, History, the text box. The ESP32-P4 has no browser. It does have a hardware JPEG decoder and a 720×1280 MIPI-DSI panel.

## Options considered
- Redraw the UI natively on the Tab5 with M5GFX, fed by `/events`. Built first as a prototype: it worked end to end, but it is a second UI to keep in step with `ui.html`, and the orb was a much plainer circle.
- Redraw it natively with LVGL: smoother widgets and fonts, the same second-UI problem.
- Stream the real page: a headless Chrome on the laptop renders `ui.html` at the Tab5's size, the DevTools screencast sends a JPEG on every repaint, the Tab5 decodes it in hardware and shows it, and its touches are replayed in the page.

## Decision
Stream the real page (`src/kiki/screen.py`). The page is 720×1200, the panel's own portrait orientation: showing a full frame takes 78 ms there against 767 ms rotated to landscape. The bottom 80 px of the panel is the Tab5's own volume bar (ADR 0031). Only the newest frame is sent, and only after the Tab5 replies `shown` to the last one, so a slow link skips frames instead of falling behind. Touches go back as `down|move|up x y` lines and become touch events in the page. A headless browser has no keyboard, so the streamed page, and only it, gets an on-screen keyboard (`screen_keyboard.js`), injected before the page loads; Chrome runs such a script only once the Page domain is enabled. The DevTools protocol runs over `websockets`, already installed with Pipecat, now used directly.

## Consequences
+ The Tab5 looks exactly like the browser UI, and there is one UI to maintain.
+ Every change to `ui.html` reaches the fridge with no reflash.
- Google Chrome must be installed on the laptop (`KIKI_CHROME` for another path) and `kiki.screen` must run next to Kiki.
- While the orb moves, about 12 frames a second of 25–35 KB each cross the Wi-Fi, and the Tab5 spends ~90 ms per frame decoding and showing it. Touch feedback waits for the next frame.
- Typing needs the injected keyboard. A native UI on the Tab5 is being tried; it gets its own ADR if it replaces this.
