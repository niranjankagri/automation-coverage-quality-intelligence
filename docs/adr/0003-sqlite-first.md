# ADR 0003: SQLite for the execution history

Status: Accepted (2026-10-20)

## Context

Trends, recurring failures and flaky-test candidates need results from many runs. The store
must work on a laptop, in a CI job and for a reproducible demonstration from a clean checkout.

## Decision

Use SQLite through Python's standard `sqlite3` module, one file (default `.qi/quality.db`,
setting `QI_DATABASE`). Keep SQL in the `history` package only, so another database could
replace it there without touching the analysis code.

Add PostgreSQL only when there is a demonstrated need, for example several CI jobs writing
at the same time or a shared server-hosted dashboard.

## Consequences

- No database server to install or start.
- One writer at a time. In CI the history file is passed between runs as an artifact or cache;
  concurrent writers are not supported and the documentation says so.
