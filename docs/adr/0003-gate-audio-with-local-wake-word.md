# 0003. Gate audio with a local wake word ("hey jarvis") before STT

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.11, NFR-0.1, NFR-0.2

## Context
Privacy requires that nothing is transcribed or sent before the wake word. A transcript-matching wake phrase would run STT on everything it hears.

## Options considered
- Wake phrase matched on transcripts: simple, but transcribes everything.
- openWakeWord with a built-in model ("hey jarvis", "alexa", "hey mycroft", "hey rhasspy"): local, runs on raw audio.
- openWakeWord with a custom "hey Kiki" model: nicer, needs training and tuning.

## Decision
openWakeWord with the built-in "hey jarvis" model, as a processor in front of STT. "hey Kiki" is a later idea.

## Consequences
+ Nothing reaches STT before the wake word.
- "hey jarvis" isn't our name. Must verify openWakeWord fits as a Pipecat processor (open check in ROADMAP).
