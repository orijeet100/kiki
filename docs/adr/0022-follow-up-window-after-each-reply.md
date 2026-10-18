# 0022. Listen for five seconds after each reply, with the previous command as context

- Status: Reverted in v0.7: with a movie playing, background speech kept it listening and answering. Superseded by 0025
- Date: 2026-10-17
- Related: FR-0.16, NFR-0.1. Amends 0009 (single-turn) and 0016 (one command per wake word).

## Context
"I want to add chicken." [pause] "and eggs" was half lost. "I want to add chicken" is a finished sentence in both words and intonation, so no end-of-turn model can know more is coming; the gate had closed and "and eggs" was never heard. People avoid this by letting the speaker carry on.

## Options considered
- A longer silence before ending every command: slows every command.
- Recover from a false end (cancel and re-run with the joined sentence if speech resumes): most natural, but the first command's changes are already applied, so it needs held-back changes. Later (v1 idea).
- A follow-up window like Alexa's Follow-Up Mode and Google's Continued Conversation: keep listening a few seconds after each reply, no wake word needed.

## Decision
After each spoken reply, the wake gate listens for `KIKI_FOLLOW_UP_SECS` (5 s), starting 0.3 s after playback ends so the tail of Kiki's own voice isn't heard. There's no chime when the window opens or expires unused (the orb shows "Listening…"). A command that starts in the window goes to the agent with the previous command as context ("and eggs" after "add chicken" means add eggs; never repeat the earlier changes). The window isn't opened over an interrupted reply, where the wake session is already listening.

## Consequences
+ Split commands and bursts ("also add eggs", "and rice") work without repeating "hey jarvis".
+ List changes add up, so a command split in two still leaves the right list.
- Speech in the room during the window (TV, other people) is transcribed and may be taken as a command. NFR-0.1 now names this exception.
- Speaking while Kiki is still thinking or talking is still lost; that needs false-end recovery or echo cancellation.
