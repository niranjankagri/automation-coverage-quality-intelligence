# ADR 0001: One Python package (modular monolith), not services

Status: Accepted (2026-10-20)

## Context

The platform reads result files, links them to requirements, stores history, evaluates gates
and shows a dashboard. A typical input is a few hundred to a few thousand test results per run.
It runs inside a CI job and on a laptop.

## Decision

Build one installable Python package with one sub-package per responsibility (`models`,
`ingest`, `traceability`, `history`, `gates`, `dashboard`) and one command (`qi`). The
boundaries are enforced by a test that parses imports (`tests/architecture/test_layering.py`),
not by network calls.

Python because the data handling (XML parsing, SQLite, small calculations) is well supported in
the standard library and the typing is good enough for `mypy --strict`.

## Consequences

- A CI job needs only `pip install` and one command; no containers or service start-up.
- Calculations are plain functions, tested directly and fast.
- If one part ever needs to scale on its own, the package boundary is already the seam to split
  along. There is no such need now.
