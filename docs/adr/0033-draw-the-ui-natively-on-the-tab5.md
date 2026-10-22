# 0033. Draw the UI natively on the Tab5 with LVGL, alongside the streamed page

- Status: Proposed (the owner is testing it; if adopted it supersedes 0028)
- Date: 2026-10-22
- Related: FR-0.13, ADR 0027, ADR 0028, ADR 0029, ADR 0030, ADR 0031

## Context
The streamed page (ADR 0028) looks exactly like the browser but felt clunky on the fridge: about 12 JPEG frames a second, every tap waiting for the next frame, and Chrome running on the laptop. The owner asked for a native UI with the same features and the same orb, as smooth as the web version.

## Options considered
- Keep streaming, tune it: still bound by Wi-Fi and by decoding and showing a full frame (~90 ms).
- Native with M5GFX alone: the first prototype; plain fonts and a plain circle for an orb.
- Native with LVGL 9 on M5GFX: anti-aliased fonts, widgets (keyboard, scrolling, sheets), partial redraws.
- Native with ESP-IDF and Espressif's LVGL port: double-buffered panel and LVGL's own PPA support, but a different tool chain (estimated 2–4 days).

## Decision
LVGL 9.6 on the Arduino setup of ADR 0032, in `device/kiki`, as an alternative to `device/stream`. It reads Kiki's own events (`GET /events` on `KIKI_UI_HOST=0.0.0.0`) and sends taps and typed commands back (`POST /item`, `POST /command`); the mic and speaker are those of ADRs 0029–0031. The text is Inter (SIL OFL) at four sizes, converted with `lv_font_conv`, at 1.5× the web's pixel sizes so it reads across a kitchen. The orb is a port of the Speaking Orb's particle maths (MIT, notice kept): 3,000 particles drawn at half resolution on the second core and scaled up 2× by the P4's PPA straight into the panel, with lookup tables and single-precision maths. LVGL redraws only what changes and leaves the orb's rectangle alone.

## Consequences
+ Measured on the Tab5: the orb at ~40 fps (listening, thinking) and ~36 fps (speaking), a tap opens the keyboard in 17 ms and flips an item in 10 ms, with the mic still at 502 packets per 10 s.
+ No Chrome and no `kiki.screen` on the laptop; nothing but Kiki's events and audio on the Wi-Fi.
- A second UI to keep in step with `ui.html` by hand.
- The half-resolution orb is slightly softer than the web's (`ORB_RENDER_SCALE = 1`: sharp, ~21 fps); no double buffering on the panel (a patch to M5GFX or the ESP-IDF move); the caption's particle flight isn't ported; chips show "now" where the web shows an arrow, which Inter's subset lacks.
- New device dependencies: LVGL 9.6.0 (MIT), ArduinoJson 7.4.3 (MIT), Inter (OFL 1.1, licence in `device/kiki/src`), and `lv_font_conv` 1.5.3 at font-conversion time only.
