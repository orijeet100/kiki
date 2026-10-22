# 0030. The Tab5's mic and speaker take turns

- Status: Accepted
- Date: 2026-10-21
- Related: FR-0.29, FR-0.30, FR-0.12, ADR 0029

## Context
On the Tab5 the mic (ES7210) and the speaker (ES8388) share one I2S port: the same bit, word and master clock pins. M5Unified sets them up as two separate channels on that port, each driving its own clock. Running both at once was tried, at 16 kHz to match: the mic kept recording and heard a test tone, which looked like success, but the speaker played garbled, very loud noise. The owner heard a screech, then choppy, distorted replies, then loud noise again, all in that mode.

## Options considered
- Take turns, as M5Unified is designed: end the mic, begin the speaker, play, switch back.
- One full-duplex I2S channel set up by Kiki's own code, with one shared clock: Kiki could hear "hey jarvis" while the Tab5 speaks. More code, more risk, and echo cancellation would still be needed, since the Tab5's mic hears its own speaker loudly.

## Decision
Take turns. The mic runs by default. When Kiki's audio arrives, the Tab5 ends the mic and begins the speaker; 200 ms after the last sample has played it ends the speaker and starts the mic again. The speaker runs at M5Unified's default 48 kHz and resamples Kiki's 16 kHz itself.

## Consequences
+ Clean sound, confirmed by the owner's listening test.
+ The Tab5 never hears its own voice, so there is no echo to cancel.
- "Hey Jarvis" can't interrupt Kiki while the Tab5 speaks (FR-0.12 still works with the laptop's mic).
- The mic is paused during the chime (about half a second): say "Hey Jarvis", wait for the chime, then the command.
- Full duplex with a shared clock and echo cancellation is listed in the ideas.
