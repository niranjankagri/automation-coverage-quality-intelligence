# M13 gap analysis: advanced quality intelligence

Audit of the code before M13 (branch `feature/m13-quality-intelligence`), item by item against the
plan. The plan's acceptance rule applies to everything M13 adds: **every classification and
recommendation links to its supporting executions and documented calculation.**

## Baseline

| Item | Value |
|---|---|
| Code | `c8370db` (`main`, deployed) |
| Live data (2026-10-23 04:00 UTC) | 422 runs, 42 synthetic requirements, 44 test cases |
| Tests before M13 | 1,023 unit/integration/architecture |

## Items

| # | Plan item | State at `c8370db` | Where today | M13 |
|---|---|---|---|---|
| 1 | Regression detection between comparable builds | **partial** | `history/builds.py` compares two builds the user picks; Needs Attention lists *newly failing* tests per context | find the previous comparable build by itself and list what regressed, with both runs linked |
| 2 | Rank recurring failures by frequency and recency | **partial** | `recurring_failures()` sorts by runs, then occurrences; recency is ignored; the table links no run | documented rank (recent runs first), first/last seen, links to the supporting runs |
| 3 | Persistent performance regressions | **done** | `duration_regressions()`: every one of the last 2 runs above baseline x1.5 and +1 s (docs/metrics.md) | reuse; link the runs |
| 4 | Transparent release-readiness scorecard | **partial** | `readiness.py`: one state and its reasons | one row per criterion: value, threshold, result, evidence link |
| 5 | Quality-gate changes over time | **missing** | the gate is evaluated on the current snapshot only | evaluate the gate on each daily snapshot and list when the verdict or a rule changed |
| 6 | Prioritise coverage gaps by criticality and ownership | **partial** | Overview and Needs Attention list gaps; critical gaps are a finding kind | documented order (criticality, then automation status), grouped by owner |
| 7 | Repository-level quality trend summaries | **partial** | `RepositoryHealth` shows the current state per repository; trends are per run context | per repository: pass rate and failing tests now vs 7 days earlier, from daily snapshots |
| 8 | Daily quality digest from actual history | **missing** | – | `qi digest` + `/api/digest`: what changed since the previous day, each line linked |
| 9 | GitHub issue suggestions for recurring failures, approval before creation | **missing** | – | a draft issue (title, body with evidence links) and a pre-filled *new issue* link; the app never creates issues |
| 10 | AI-assisted summaries after deterministic metrics are verified | **deferred** | – | not in M13: no API key on the deployment, and the plan puts deterministic metrics first; the digest and summaries are deterministic |

## Rules kept from earlier milestones

- Read-only API (`GET` only); the dashboard never writes to GitHub.
- Calculations live in the core packages, not in the dashboard (architecture test).
- Synthetic requirements stay labelled as synthetic; executions are real CI results.
- A rule that cannot decide says *unknown*; missing evidence never counts as good.
