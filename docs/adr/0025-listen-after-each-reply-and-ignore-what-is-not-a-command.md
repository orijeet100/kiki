# 0025. Listen for five seconds after each reply, and stay quiet if what's heard isn't a command

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.18, NFR-0.1. Supersedes 0022 (reverted). Amends 0016 (one command per wake word). Keeps 0009 (single-turn).

## Context
The owner wants to say another command right after a reply without "hey jarvis" again. ADR 0022 did this in v0.6, but was reverted: with a movie playing, speech in the window was transcribed and answered ("Sorry, I didn't catch that."), and every reply opened a new window, so Kiki kept listening and talking to the movie.

## Options considered
- Minimum loudness for follow-up speech: needs tuning per room; a loud TV still passes.
- One follow-up per wake word: stops loops, but also stops a real burst of commands.
- A chime when the window opens: tells you it's open, but doesn't stop the movie.
- Silent on non-commands: if what's heard in the window isn't a grocery command (the agent's "Sorry, I didn't catch that."), say nothing and change nothing. With no reply, no new window opens.
- The previous command as context (as in 0022): makes "and eggs" continue "add chicken", but breaks single-turn (0009).

## Decision
Silent on non-commands, with standalone commands (the owner's choice). After each spoken reply the wake gate listens for `KIKI_FOLLOW_UP_SECS` (5 s), starting 0.3 s after playback ends so the tail of Kiki's own voice isn't heard, with no chime (the orb shows "Listening…"). A command heard in the window is an ordinary single-turn command. If the agent can't tell what it means, Brain logs the turn with nothing said and goes idle. The window isn't opened over an interrupted reply, where the wake word's session is already listening.

## Consequences
+ "Add eggs" right after a reply works without the wake word, and so does a burst of commands.
+ Background speech gets at most one silent hearing per reply; a movie can't keep Kiki talking.
+ Still single-turn: no conversation state.
- Speech in the window is transcribed and sent to the model; NFR-0.1 names this exception.
- Background speech that sounds like a grocery command ("add the eggs") is acted on.
- A bare "and eggs" depends on the model reading it as "add eggs"; it has no previous command.
