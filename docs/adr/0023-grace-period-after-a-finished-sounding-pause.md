# 0023. Wait a short grace period after a pause sounds finished

- Status: Accepted (shipped in v0.6, removed with the v0.6 revert, restored on its own without the follow-up window)
- Date: 2026-10-17
- Related: FR-0.14. Amends 0021 (when the command ends).

## Context
With real-time-paced test audio, "Add milk, two apples and some rice." lost everything after "milk": the comma is a 0.3 s pause, Smart Turn judged "Add milk," finished, and the command ended. Moving the check to 0.5 s of silence fixed commas but broke thinking pauses: Smart Turn, trained to judge at about 0.2 s, then called "Can you add one ..." finished in 3 of 4 runs.

## Options considered
- Check at 0.2 s and end at once: list commas cut commands off.
- Check at 0.5 s: thinking pauses cut commands off.
- Check at 0.2 s; if it sounds finished, wait `KIKI_END_GRACE_SECS` (0.4 s) more and end only if nobody speaks.

## Decision
The third. Speech within the grace period (VAD reports it about 0.2 s after it resumes) keeps the same command going.

## Consequences
+ Both list commas and thinking pauses are handled; repeated runs of both voice tests pass.
- A finished command ends about 0.66 s after the last word (0.26 s in 0.5), still faster than the original 0.8 s.
