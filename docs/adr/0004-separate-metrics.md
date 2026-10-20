# ADR 0004: Coverage and pass rate stay separate metrics

Status: Accepted (2026-10-20)

## Context

"Coverage" is used loosely for very different things. A single blended score hides which
problem a team has: missing tests, tests that are still manual, or tests that fail.

## Decision

Report at least three separate numbers, each with its own documented formula and denominator
(the exact formulas are defined in Milestone 2 and documented in `docs/metrics.md`):

- **Requirement coverage**: share of requirements that have at least one linked test case.
- **Automation coverage**: share of linked test cases that are automated.
- **Execution pass rate**: share of executed automated tests that passed in a given run.

No combined "quality score". When a denominator is zero the metric is reported as "not
applicable", never as 0 % or 100 %.

## Consequences

- Dashboards and reports show three numbers instead of one; each one points to a different action.
- Quality gates set a threshold per metric.
