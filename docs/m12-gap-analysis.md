# M12 gap analysis: interactive investigation

Design audit of the dashboard before M12 (branch `feature/m12-interactive-investigation`, built on
the M11/M14 branch of PR #5). M11/M14 and M12 are now merged into `main`; this file records the
baseline and implementation decisions. PR #9 reviews the merged behavior and closes concrete
issues found without duplicating completed capabilities.

## Baseline

| Item | Value |
|---|---|
| Code | `5486d17` (PR #5 head; `main` is `ab5bebd`) |
| Live data (2026-10-21 05:05 UTC) | see *Data volume* below |
| Tests before M12 | 947 unit/integration/performance, 104 browser (Chromium; Firefox 103 + 1 skip, WebKit 102 + 2 skips) |
| Response times | [performance.md](performance.md); live: readiness 0.24 s, stability 0.33 s, tests 0.89 s (warm, 04:26 UTC) |
| Frontend | vanilla JavaScript (`static/app.js`), hash routes, every value written as text, strict CSP |
| API | read-only `GET` routes, FastAPI, views built from one immutable workspace per data snapshot |

## Capabilities

| Capability | State | Where today | M12 |
|---|---|---|---|
| Filters (repository, feature, owner, criticality, type, framework, environment, browser, build, job, dates) in the URL | **done** | filter bar, chips, copy link | reuse |
| Sorting, row filter, CSV, paging, column chooser | **done** | `table()` | reuse |
| Row filter of the Tests table ("part of the name") | **partial** | Tests page only | global search across entity types |
| **Global search** (repositories, workflows, pipelines, run ids, tests, requirements, failure messages) | **missing** | – | `/api/search`, Search page and header entry |
| Overview gaps: critical without automation, failing requirements, other gaps; readiness with reasons | **done** | Overview | link from Needs Attention |
| Flaky candidates with evidence; recurring failures; duration regressions | **done** (separately) | Stability page, `/api/stability` | consolidate |
| Incomplete pipelines, missing artifacts, overdue repositories | **done** (separately) | Pipelines, Collection | consolidate |
| **Needs Attention** (one list, evidence counts, first/last seen, state, why flagged) | **missing** | – | `/api/attention`, Needs Attention page |
| Newly failing tests (failed now, passed in the previous execution of the same suite) | **missing** outside Compare | Compare (between two chosen builds) | per suite, latest vs previous execution |
| Repository → workflow → pipeline → job → run → test navigation | **partial** | links exist on each page, no single chain, no breadcrumbs | breadcrumbs, pipeline focus by id |
| GitHub run and commit links | **done** for pipelines and test executions | Pipelines, test history | also on build comparison and investigation |
| Test investigation: latest result, context, pattern, requirements, executions with CI links, duration chart, copy id and link | **done** | test history page | add workflow/repository, previous outcome, flakiness evidence, execution selection, comparison of two executions, long failure text collapsed, summary |
| Build comparison: newly failing, recovered, still failing, added, removed, slower, newly flaky; incomparable explained | **done** | Compare | add count differences, CI links of each build, incomplete-pipeline note, summary |
| **Copyable investigation summary** (text and Markdown, deterministic) | **missing** | – | built in the backend, copied in the page |
| Issue-tracker links | **missing** | – | not in this PR (the plan says no external issues); a summary can be pasted into one |
| Accessibility: WCAG checks, keyboard, reduced motion, themes, focus, 3 engines, layout tests | **done** | tests/e2e | extend to new pages |

## Data volume

Live site, 2026-10-21 07:08 UTC: 258 runs, 1,943 distinct tests, 74 collected pipeline attempts
from 23 repositories, latest collection 03:09 UTC. Warm response times measured from India:
summary 0.25 s, readiness 0.45 s, stability 0.35 s, tests 0.58 s, pipelines 0.75 s, trends 0.91 s.
The search index of that history has 2,095 entries.

## Built in M12

All gaps above except issue-tracker links (left out on purpose: no external issue is created;
a copied summary can be pasted into one). Tests: `tests/unit/test_search.py`,
`tests/unit/test_attention.py`, `tests/unit/test_investigation_summary.py`, API tests in
`tests/unit/dashboard`, `tests/e2e/test_investigation.py`, new pages in the accessibility, layout
and phone-width checks, budgets in `tests/performance`.

## Decisions

- **No new framework, no new storage.** Search and Needs Attention are computed from the
  workspace (already in memory for each snapshot) and cached per snapshot like the other views.
- **Search index per snapshot**, not per keystroke: entries are built once, a query filters them.
  Queries are bounded (2-100 characters, at most 20 results per group with full counts).
- **Findings say what the evidence shows.** *Open* only when the latest execution still shows
  the problem; *resolved since* when a later execution passed; *unknown* when there is no later
  evidence. Flaky candidates stay *suspected*.
- **Summaries are built in the backend** from the same data as the page, so they are
  deterministic and testable; they never state a cause, only observations and their limits.
