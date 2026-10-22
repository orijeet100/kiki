# 0032. Device code lives in this repo, one Arduino sketch per folder under `device/`, built with arduino-cli

- Status: Accepted
- Date: 2026-10-21
- Related: ADR 0027, AGENTS.md rules 4 and 6

## Context
The Tab5's program and Kiki speak protocols defined on both sides (ports, packet sizes, the `shown` reply, touch lines). A change to one side usually needs the other.

## Options considered
- A separate repository for the device: its own history, but both sides drift unless kept in step by hand.
- ESP-IDF or PlatformIO: more control, a heavier tool chain to set up.
- Arduino sketches built with `arduino-cli` and M5Stack's board package, in this repo; the same sketches open in the Arduino IDE 2.

## Decision
`device/` in this repo, one sketch per folder (Arduino requires the folder and the `.ino` to share a name): `device/check` (screen, touch, mic and speaker check) and `device/stream` (the Tab5 program: streamed screen, mic, speaker, volume bar). Each folder's `secrets.h` holds the Wi-Fi password and the laptop's IP and is git-ignored; `secrets.h.example` is committed. Tools: `arduino-cli` 1.5.1, board package `m5stack:esp32` 3.3.10 (board `M5Tab5`), libraries M5Unified 0.2.27 and M5GFX 0.2.34. uv, pytest and ruff ignore `device/`.

## Consequences
+ A protocol change lands in one commit on both sides; one tag covers a laptop and a Tab5 build that work together.
- The Tab5 program has no automated tests; it is checked by hand on the device (ROADMAP, definition of done). The laptop's side of every link is tested (`tests/test_tab5.py`).
- Flashing needs the Tab5 on USB; a Tab5 that is in download mode (Reset held for 2 s) needs a short press of Reset afterwards to start.
