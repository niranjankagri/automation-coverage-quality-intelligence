# Report UI (`/next/`)

A new front end for the same data, shaped like an **Allure report**, at `/next/`. It is being built
beside the current dashboard (`/`), which stays the main page until the new one covers everything
and the owner switches them. Nothing in the engine changes: the report reads the same read-only
JSON API, and where it needs data shaped differently it gets one more `GET` route.

## Why

The current dashboard is organised by data type (tests, runs, pipelines, requirements, builds …)
in about 17 navigation entries; people arrive with a question and have to find the page that holds
the answer. An Allure report is easy to read because it does a few things consistently: a short
sidebar that never moves, an overview that answers "how did it go" at a glance, failures grouped
by cause, and a tree with the selected test's details beside it.

## Decisions (owner, 2026-10-23)

- **Fresh front end in the same project, on the existing data.** No new framework or build step:
  plain JavaScript modules (`static/next/js/`), the same strict Content Security Policy.
- **Separate address first.** `/next/`; the current UI stays at `/` until the owner says the new
  one looks good, then it replaces the main page.
- **Allure structure:** left sidebar with Overview, Categories, Suites (two panes: tree + test
  details), Graphs, Behaviors (requirements); tools such as Pipelines, Collection, Compare and Search
  stay reachable but out of the main navigation. Timeline is left out for now.
- **Repository switcher at the top, "All repositories" by default** (one report per repository, or
  all of them together).
- **The portfolio's design.** Visitors come from niranjankagri.github.io, so the report uses its
  colours, contrast, type and light/dark behaviour exactly (tokens copied into
  `static/next/report.css`; the theme button and the `na-theme` storage key work like the
  portfolio's). The portfolio itself is not changed by this work.

## Status

| Section | State | Data |
|---|---|---|
| Overview | **built** | `GET /api/report/overview`: the latest snapshot (latest run of each suite) as totals and pass rate, suites (a repository, or a framework for files that were not collected), failure categories (failed and error results grouped by failure signature, [metrics.md](metrics.md#recurring-failures)), the daily snapshot trend of the last 14 days with runs, and the environment |
| Categories | next | recurring failures and issue drafts ([issues.md](issues.md)) |
| Suites | **built** | `GET /api/report/suites`: the same snapshot as a tree, repository (or framework for files not collected) > pipeline job (or run context) > class > test, with counts per level. Left pane: the tree with a name filter and status chips; right pane: the selected test from `/api/tests/history` (latest result and failure, the pass/fail pattern, stability, executions with run and CI links, requirements). The selection is in the address (`#/suites?test=...`), so Back works and a test can be shared |
| Graphs | next | trends, durations, regressions, gate history |
| Behaviors | next | requirements, coverage, gaps by owner |

A section that is not built yet says so and links the classic page that has the data today. The
Overview's figures are the classic coverage page's (a test compares them), so both UIs always agree.

## Checks

`tests/e2e/test_report_ui.py`: the Overview on the samples (221 results, 100 % pass rate, four
suites), the Suites tree (221 tests, a selected test kept on reload, name and status filters), the repository switcher on collected data (address kept on reload), a section still to
build links its classic page, the theme button like the portfolio's, axe-core WCAG 2.2 A/AA in both
themes, and a phone width without sideways scrolling. API tests in `tests/unit/dashboard/test_api.py`
check the overview against `/api/summary`, the grouping of failures by cause and of collected runs by
repository, and how `/next/` is served (policy, revalidation, redirect from `/next`).


### Installed deployment guard

The report's files live below `dashboard/static/next/`, so package-data patterns explicitly
include that directory and `next/js/`. A top-level `dashboard/static/*` pattern alone omits
them from the wheel: editable source tests pass, but `/next/` raises HTTP 500 after installation.
CI builds a real wheel and runs `tools/check_wheel_assets.py` against every source dashboard
asset, including nested folders. The container and live smoke check `/next/`, the CSS, all
current JavaScript modules and `/api/report/overview`, including MIME types for assets.
