# 0027. The Tab5 is a thin client of the laptop over the home network, with plain sockets and no password yet

- Status: Accepted
- Date: 2026-10-21
- Related: FR-0.29, FR-0.30, FR-0.31, NFR-0.7, NFR-0.8. Builds on 0007 (the laptop hosts everything). Decides the device transport that 0011 left open.

## Context
The fridge device is an M5Stack Tab5 (ESP32-P4, 5" 720×1280 touchscreen, two mics, a 1 W speaker, Wi-Fi 6 through an ESP32-C6). It can't run the wake word, Whisper, Piper or the agent, so per ADR 0007 it is only a screen, a mic and a speaker for the laptop. It needs four streams: the screen out, touches in, the mic in, and Kiki's voice out. ADR 0011 deferred the choice of transport until the hardware arrived.

## Options considered
- Pipecat's WebSocket transport with a frame serializer: one connection, but every stream shares one ordered pipe, and the Tab5 would need a WebSocket client and Pipecat's serialization.
- WebRTC: built for live audio, but there is no WebRTC stack for the ESP32-P4 worth the effort.
- Plain sockets, one per stream, each with the transport that suits it (decided in 0028 and 0029). The Tab5 is always the client and finds the laptop by a fixed IP.
- Finding the laptop by name (mDNS) instead of a fixed IP: nicer, more code on both sides.
- A shared secret on every connection: safer on a shared network, more code on both sides.

## Decision
Plain sockets, one per stream, all opened by the Tab5 to fixed ports on the laptop: the screen on 8767 (`python -m kiki.screen`), the mic on 8768 and the speaker on 8769 (`python -m kiki.voice` with `KIKI_MIC=tab5` and `KIKI_SPEAKER=tab5`). The Wi-Fi name, password and the laptop's IP live in `secrets.h`, which git ignores. The UI server can be opened to the network with `KIKI_UI_HOST=0.0.0.0` for a Tab5 program that follows `/events` itself; it then accepts requests addressed to an IP address as well as to `localhost`, and still refuses other host names, so DNS rebinding stays blocked (NFR-0.7). No password for now: the home network is trusted.

## Consequences
+ Each stream is simple and tuned on its own; restarting either side needs no handshake beyond reconnecting.
+ The Tab5 program has no dependency beyond M5Stack's libraries.
- Anything on the home Wi-Fi can send commands, read the list, or send audio to Kiki's mic port. A shared secret is needed before Kiki runs unattended (marked `ponytail:` in the code).
- The laptop's IP must not change: reserve it in the router (a DHCP reservation).
- Audio crosses the home Wi-Fi unencrypted between the Tab5 and the laptop (NFR-0.8).
