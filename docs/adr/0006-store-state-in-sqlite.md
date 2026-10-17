# 0006. Store state in SQLite

- Status: Accepted
- Date: 2026-10-17
- Related: FR-0.1 to FR-0.7

## Context
One small list, one process, one machine.

## Options considered
- JSON file: simplest, but no constraints and easy to corrupt.
- SQLite: stdlib, one file, unique constraint on `normalized_name`.
- A database server: unnecessary.

## Decision
SQLite via the stdlib `sqlite3`, file path from `KIKI_DB`.

## Consequences
+ No server, no dependency, room for pantry and cart tables later.
