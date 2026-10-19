# 0016. The wake gate lets through one utterance per wake word

- Status: Accepted; how the end of the utterance is detected is superseded by 0021; amended by 0025 (a follow-up window after each reply)
- Date: 2026-10-17
- Related: FR-0.11, FR-0.12, NFR-0.1. Implements 0003 and 0009 for voice.

## Context
After "hey jarvis" the gate must open, let the command through, and close again, so nothing else gets transcribed. Commands are single-turn (ADR 0009).

## Options considered
- Close on a fixed window (the reference repo uses 15 s, re-armed by each transcript): more audio reaches Whisper, and follow-up speech would leak into the next turn.
- Close when VAD reports the end of speech, with a short timeout if nobody speaks.

## Decision
Close at the end of the first utterance (`VADUserStoppedSpeakingFrame`), or after `KIKI_LISTEN_TIMEOUT_SECS` (6 s) of no speech. Chimes mark open and close. The wake model keeps scoring while Kiki speaks, and a wake word then interrupts the speech.

## Consequences
+ The least audio possible reaches speech-to-text; the gate's state matches "one command per wake word".
- A long pause mid-sentence ends the command. `KIKI_VAD_STOP_SECS` (default 0.8 s) is the knob.
