# 0014. Don't export or sync the list to phones

- Status: Rejected
- Date: 2026-10-17
- Related: —

## Context
A voice-only list can't be read in a store. We considered writing `grocery.txt` to a OneDrive folder after every change, or sending it via a Telegram bot.

## Options considered
- OneDrive-synced text file.
- Telegram bot message on request.
- Nothing.

## Decision
Rejected. We order groceries from home, so nobody needs the list in a store.

## Consequences
+ Nothing leaves the house except the command text sent to Claude.
- If in-store use ever matters, the synced file is about five lines of code.
