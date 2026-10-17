# 0012. Clear the list without confirmation

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.7, NFR-0.4

## Context
A two-step "are you sure? / yes" needs state across turns, which ADR 0009 rules out for v0.

## Options considered
- Two-step confirmation stored in the tool layer, expiring after 60 seconds.
- Clear immediately. `clear_list` returns the removed items, which are written to the turn log.

## Decision
Clear immediately. The log is the recovery path.

## Consequences
+ No cross-turn state.
- A false wake plus a misheard "clear" wipes the list. Recovery is manual from the log. If this ever happens, revisit with a new ADR.
