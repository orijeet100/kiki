# 0029. The Tab5's mic reaches Kiki over UDP from its own task; Kiki's voice reaches the Tab5 over TCP, paced by the clock

- Status: Accepted
- Date: 2026-10-21
- Related: FR-0.29, FR-0.30, NFR-0.8, ADR 0027

## Context
Kiki's wake word, Smart Turn and VAD keep wall-clock time, so the mic must arrive at real-time pace with nothing missing; the speaker must never run dry mid-word. The first versions failed in measurable ways:
- The mic over TCP, sent from the Tab5's main loop: each connection attempt blocked the loop for up to 2 s, the mic's 320 ms of buffers overflowed, and a third of the audio was lost; a stale connection stalled for 40 s.
- Wi-Fi power saving, on by default, lost about a quarter of the packets, with long gaps.
- Waiting up to 2 s for the laptop to read the Tab5's USB log froze the mic task whenever nothing was reading it.
- The speaker paced by sleeping 40 ms per 40 ms chunk: Windows oversleeps, Kiki fell behind real time, and replies were choppy.

## Options considered
- Mic over TCP from its own task: reliable, but a dead connection needs detecting and redialling, and a retransmitted packet is late anyway.
- Mic over UDP from its own task: no connection at all; a lost packet is 20 ms of silence.
- Speaker paced per chunk, or paced by a clock with a small lead.

## Decision
- **Mic:** the Tab5 records 20 ms at a time (320 samples, 16 kHz mono int16) into a ring of 16 buffers and sends each as one UDP packet to port 8768 from a FreeRTOS task of its own, with Wi-Fi power saving off and the USB log never waiting for a reader. Kiki's `Tab5Mic` turns each packet into an `InputAudioRawFrame` and logs how many arrived every 10 s (500 means none lost).
- **Speaker:** the Tab5 connects to port 8769. Kiki's `Tab5Speaker` sends 16 kHz mono int16 in 40 ms chunks, paced against a clock (`_played_by`) that stays `LEAD_SECS` (0.15 s) ahead of the Tab5's playback. The pipeline's output rate is 16 kHz so Piper speaks at that rate directly; only the 48 kHz chime is resampled (an output's resampler accepts a single input rate). The Tab5 buffers up to 4 s, starts playing once 160 ms are in, keeps two chunks queued on the speaker, and counts gaps per reply.

## Consequences
+ Measured: 500 of 500 mic packets every 10 s, for minutes, with the screen streaming; the chime played with 0 gaps; the owner heard replies whole.
+ Either side can restart: the mic just resumes, the speaker redials every 3 s.
- A lost mic packet is not retransmitted (on a home network this has not been seen once the fixes above were in).
- Kiki considers a reply finished about 0.3 s before the Tab5 does (the lead plus the start buffer); the follow-up window opens that much early, which the turn-taking in ADR 0030 makes harmless.
