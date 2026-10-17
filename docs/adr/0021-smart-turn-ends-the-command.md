# 0021. Smart Turn decides when a spoken command is finished

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.14, FR-0.11, NFR-0.3. Supersedes the "close at the end of the first utterance" rule in 0016.

## Context
In daily use, "Can you add one ... garlic and one onion" was cut off at the pause: VAD declared the command over after 0.8 s of silence, Whisper transcribed "Can you add one?", and Kiki said "Sorry, I didn't catch that." A fixed silence threshold can't tell a thinking pause from the end of a sentence; making it longer slows every command.

## Options considered
- Longer VAD silence (1.5 s or more): fixes some pauses, adds the same delay to every command.
- Transcribe at each pause and judge the text: an extra Whisper pass (~0.5 s) per pause.
- Pipecat's Smart Turn v3.2 (bundled ONNX model, CPU, ~60 ms): judges from intonation whether the sentence sounds finished. On Piper speech cut mid-sentence at word boundaries it said "unfinished" for 8 of 9 cuts ("Can you add one ..." scored 0.04) and "finished" for all full sentences (0.77 to 0.99).

## Decision
VAD reports every pause of `KIKI_PAUSE_SECS` (0.2 s). A new `EndOfTurnDetector` asks Smart Turn at each pause. Unfinished: the pause is hidden from Whisper and the gate stays open. Finished, or `KIKI_MAX_PAUSE_SECS` (3 s) of silence: one stop frame goes to Whisper (it transcribes the whole command once) and `UserStoppedSpeakingFrame` goes up to the wake gate, which closes.

## Consequences
+ Thinking pauses no longer cut a command off.
+ A finished sentence is recognized ~0.26 s after the last word instead of 0.8 s.
- Smart Turn can misjudge a pause as the end (1 in 9 in the test). The command is then cut off as before; saying it again works.
- Someone who stops mid-sentence for good waits 3 s for Kiki to give up.
