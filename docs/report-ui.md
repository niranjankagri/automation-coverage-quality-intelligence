# Main dashboard (`/`)

A front end for the same data, shaped like an **Allure report**, at `/`. The classic dashboard remains available at `/classic/`; `/next/` stays as a compatible
preview address. Nothing in
the engine changes: the report reads the same read-only JSON API, and where it needs data shaped
differently it gets one more `GET` route.

The reading order is **Repository → Test type → Browser / environment → Section → Evidence**: pick
what to look at in the filter bar, read the section, and every figure links to the results behind it.

## Decisions (owner, 2026-10-23)

- **Fresh front end in the same project, on the existing data.** Plain JavaScript modules
  (`static/next/js/`), no build step, the same strict Content Security Policy.
- **Main address.** `/` serves the report; `/classic/` serves the original UI. `/next/` remains available.
- **Allure structure, plain names:** Overview, Test Results, Failures & Stability, Trends, Coverage &
  Requirements. The first version's addresses (`#/suites`, `#/categories`, `#/graphs`,
  `#/behaviors`) still open the renamed sections.
- **The portfolio's identity:** its NA mark, type, rounded controls and theme button (`na-theme`),
  with slate surfaces and indigo as the report colour; green for execution success. The portfolio itself
  is not changed by this work.

## Navigation

| Part | What it does |
|---|---|
| Filter bar | Repository, Test type, Browser, Environment, From/To dates. Choices come from `GET /api/report/options` (combinations with latest results), so it never offers an empty one. Browser and environment appear only when there is more than one to choose (an API job in one browser needs no choice). Changing a parent drops child choices it does not have. Active filters are removable chips, with **Reset all**. A typed address with a combination no run has says so. On phones the bar folds behind a **Filters (N active)** button |
| Freshness | Next to the filters: when the data was last collected, incomplete collections in the last 7 days, a stale collection (older than 30 hours) or a failed reload, and **Refresh** |
| Addresses | Everything is in the address: section, scope (`repository`, `kind`, `browser`, `environment`, `job`, `since`, `until`), search and status filters, the selected test and run, the open tab. Reload, Back/Forward and shared links show the same thing; Back returns to the same scroll position |
| Loading | A section shows a skeleton at once (never the previous section's content under a new heading); a newer navigation cancels older requests; a failed request says why, with **Retry** |

**Test type** is the execution family from the job naming conventions (`execution_kind`: `api`,
`unit-*`, `ui-*`, `a11y-*` …; anything ambiguous is "Other"), because collected runs carry no other
reliable type. It is a run filter (`kind=`) on every API route, like `browser=`.

## Sections

| Section | Shows | Data |
|---|---|---|
| Overview | Four headline figures kept apart: **execution pass rate** (latest results; skipped not counted; change against the previous day), **automation coverage** (automated catalog test cases), **critical gaps**, **release readiness**. Each opens its evidence. A results donut (each status opens those results), the execution trend (each day opens that day's results), browser comparison (results, pass rate, recorded time per browser), feature coverage (covered and run / not run here / not automated / no tests per product), **Needs attention** (new failures, flaky candidates, critical gaps, slower tests, data problems), the readiness explanation and scorecard, and the selected scope (repositories with their latest branch, commit and CI run) | `/api/report/overview`, `/api/summary`, `/api/readiness`, `/api/requirements`, `/api/stability` |
| Test Results | The latest result of every test: a tree of repository > job (with its browser and environment) > class > test; with a search or status filter a flat list, 50 at a time with **Load more** and "Showing X of Y" | `/api/report/suites` (each test carries its run id; each job its type, browser, environment, platform) |
| Test details | One execution of one test: name, where it ran, outcome and time, date, commit and CI run, then tabs **Selected execution**, **History** (in this context, then across all contexts), **Browser comparison** (latest result per context), **Evidence** (failure output; screenshots, videos and logs are not collected, so the page links the CI run that keeps them). **Back to results** keeps the filters and scroll position | `/api/tests/history` in the execution's context and without one |
| Failures & Stability | Failing now, grouped by cause: *failed check* (an assertion did not hold: product, test or environment) and *error* (the test could not run as written), never labelled a product defect; unstable tests (consistently failing, new failures, flaky candidates); **recovered** tests shown apart and not counted as unstable; recurring causes with a pre-filled GitHub issue | `/api/report/overview`, `/api/stability`, `/api/issue-suggestions` |
| Trends | Results and pass rate per day, suite time per day (a day without recorded durations shows "–", not zero), how long the latest tests take, the slowest tests per job and browser, tests getting slower, the release gate per day. Each day opens its results; every chart has its numbers | `/api/trends`, `/api/report/suites`, `/api/stability`, `/api/gate-history` |
| Coverage & Requirements | Product > feature > requirement with its status in this scope, coverage figures, gaps by owner (riskiest first). A requirement opens inside the report with its test cases and the executions in scope | `/api/summary`, `/api/requirements`, `/api/gaps`, `/api/requirements/{id}` |

## Data rules

- **Pass rate is not coverage.** The pass rate counts latest results; automation coverage counts
  automated catalog test cases. They sit in separate cards with their own denominators.
- **No results is not 100 %.** A scope without verdicts (none, or only skipped) shows "No results".
- **A missing duration is not zero.** Untimed results are "not recorded" and counted apart in the
  browser comparison and the duration buckets; a day without durations has no time (`timed_results`).
- **A failure is not a product defect** until its cause says so.
- **Recovered is not unstable.** It is listed separately.
- **The catalog is labelled.** Requirements come from the synthetic sample catalog; filters narrow the
  execution evidence (what ran), never which requirements exist. A scope whose results link to no
  requirement shows **Coverage not mapped**.
- **Empty means something specific:** no collected data, nothing matching the filters, an unsupported
  filter combination, coverage not mapped, or no failures — each says which.

## Checks

- `tests/e2e/test_report_ui.py`: headline figures on the samples; donut, trend and headline cards
  open their evidence; repository → test type → browser with parent resets, chips and Reset all; an
  unsupported combination; the same test in Chrome, Firefox and Edge opens its own execution (the
  confirmed defect: a Firefox row opened another browser's run); Back, Forward, reload and a shared
  link keep the selection; keyboard tabs; Load more; the newest of quick navigations wins; old
  addresses; a requirement inside the report. Edge cases (`edge_url`): skipped-only, a failed check,
  recovered vs unstable, stale and incomplete collections, coverage not mapped, missing durations.
  axe-core WCAG 2.2 A/AA on every section, a test and a requirement in both themes; every section at
  phone width; visible keyboard focus; reduced motion.
- `tests/unit/dashboard/test_api.py`: report options, the `kind` filter, run identity per test,
  the browser comparison with untimed results, `timed_results`, branch and commit per repository.
- `tools/screenshots.py`: every section on a desktop and a phone (`docs/images/report-*.png`).
- **After each deployment** (`.github/workflows/deploy-smoke.yml`): once CI passes on `main`, wait
  until the live service reports that commit (`tools/smoke.py --expect-commit`), then check health,
  all report routes and assets, repository selection, a test drill-down into its own execution and
  a requirement drill-down over HTTP, and the same in a browser with no application errors
  (`tools/report_smoke.py`).

### Installed deployment guard

The report's files live below `dashboard/static/next/`, so package-data patterns explicitly
include that directory and `next/js/`. A top-level `dashboard/static/*` pattern alone omits
them from the wheel: editable source tests pass, but `/next/` raises HTTP 500 after installation.
CI builds a real wheel and runs `tools/check_wheel_assets.py` against every source dashboard
asset, including nested folders. The container, live and deployment smoke check `/next/`, the CSS
and every JavaScript module, including MIME types.

### Colour

Light surfaces and indigo interaction accents; the portfolio's teal for its NA mark. Passed
chart segments use green; failures stay red, errors amber and skips grey; green marks success.
Counts and labels remain authoritative; colours do not change results or release decisions. Light,
dark and system themes share one layout; motion only plays when the system allows it.

### Workspace visual refresh

Horizontal navigation frames bright, quiet content panels. The overview introduces the selected
scope, then four independent metrics, results and trends. Browser comparison uses clickable
progress cards with result counts and recorded durations; an expandable exact-number table stays
available. Phone layouts use two compact metric columns and a horizontally scrolling section bar.
The NA identity, theme preference, evidence links and scope semantics remain shared with the report.

Deployment smoke has a 90-minute job budget: browser setup can take 45 minutes, and waking the
service and waiting for the expected commit can each take 20. A skipped job is not evidence that
the deployed report passed smoke; the live URL variable must be configured.

### Approved Light Studio / Portfolio Canvas hybrid

The main page combines horizontal navigation, a restrained portfolio-style hero, white analytics
panels and green pass-rate charts. Coverage remains blue so execution success and automation
coverage have different visual meanings. Dark mode keeps contrast and the same information order.

The original report address `/next/` still serves the same report, preserving its hash and filters.
Legacy operational pages and execution run links now target `/classic/#/...`; digest and issue
draft links follow that path too. The classic dashboard includes a link back to the new home.
Deployment smoke checks the report at `/` and verifies the classic page separately.
