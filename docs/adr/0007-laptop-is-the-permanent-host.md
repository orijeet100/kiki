# 0007. The laptop is the permanent host; devices are thin clients

- Status: Accepted
- Date: 2026-10-17
- Related: NFR-0.2

## Context
The fridge device (M5Stack CoreS3 class) is too small to run wake word, STT, TTS and the agent.

## Options considered
- Self-contained device (Raspberry Pi 5): independent, more cost and setup.
- Thin device streaming to the laptop: cheap device, all logic in one place.
- A dedicated always-on mini PC: more reliable, another machine to buy.

## Decision
The laptop hosts everything, now and after hardware arrives. The device is only a mic, speaker and screen.

## Consequences
+ One codebase on one machine.
- Kiki works only while the laptop is on and online.
