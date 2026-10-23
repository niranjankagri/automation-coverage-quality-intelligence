# Changelog

## Unreleased

- **M13, advanced quality intelligence** ([docs/m13-gap-analysis.md](docs/m13-gap-analysis.md)):
  recurring failures ranked by runs in the last 7 days, then all runs, with their supporting runs;
  latest regressions per suite and branch (`/api/regressions`); a release-readiness scorecard with
  one row and evidence page per criterion; the release gate on each day's snapshot and the days it
  changed (`/api/gate-history`); coverage gaps by criticality, risk and owner (`/api/gaps`);
  repository trends, newest day against 7 days earlier (`/api/repository-trends`); a daily quality
  digest (`qi digest`, `/api/digest`); issue drafts for recurring failures that a person submits
  through GitHub's own form, never created by the dashboard (`/api/issue-suggestions`). AI
  summaries stay deferred. Every new figure links its executions and documents its calculation.
- Error badges, error dots and the error ranking no longer pick up the error-message box style
  (`.error` is scoped to `[role="alert"]`).

- Make the default dashboard a portfolio-styled visual experience: repository → test family →
  browser/job navigation, interactive result donut, day drill-downs and visual test rankings.
  Keep tables/CSV and advanced tools available on demand, and move release coverage to
  `#/coverage`. Add observed-context API, family filtering and cache revalidation for assets,
  with browser/API/smoke coverage.

- Add a historical Test execution dashboard with UTC daily outcome charts, status distribution,
  suite and shared run filters, top 10/25/100 duration/failure/error rankings and test-history
  drill-downs. Preserve unknown timings and distinguish summed test time from wall-clock time
  and test outcomes from cancelled/incomplete pipeline evidence.

- **CI collection** (`qi collect`, [docs/collection.md](docs/collection.md),
  [ADR 0007](docs/adr/0007-ci-collection.md)): a producers file names, per job, the artifact
  and the one path to import; completed runs of four public repositories are collected as
  pipeline executions (pipeline id `<repository>#<run id>`, attempt, branch, commit), one
  transaction per attempt with a collection record (GitHub conclusion, complete/incomplete,
  problems); idempotent; transient failures are retried, not recorded; artifacts unpacked
  safely; daily ingestion audit; `qi gate --database --pipeline` decides on a collected
  pipeline; scheduled workflow `collect.yml`. History schema 4.
- **Dashboard refresh without restart** (`qualityintel/live.py`, [docs/dashboard.md](docs/dashboard.md)):
  sources are fingerprinted and rebuilt into a complete snapshot when they change (`--refresh`,
  `QI_REFRESH_SECONDS`, default 30 s); a failed rebuild keeps the last good data and is shown as
  stale; `/api/status`; freshness bar with auto-refresh and Refresh; filters and address kept.
- **Release status on the overview** ([docs/readiness.md](docs/readiness.md)): Ready / At risk /
  Blocked / Unknown from the release gate given with `qi dashboard --gate` plus flaky candidates,
  incomplete pipelines and stale data; unknown evidence is never ready; `/api/readiness`.
- **Interactive investigation (M12)**: global search (header and Search page: tests, failure
  messages, requirements, pipelines and GitHub run ids, workflows, repositories; grouped, counted,
  bounded, filters apply); Needs Attention (newly failing, incomplete pipelines, critical gaps,
  recurring failures, slowdowns, flaky candidates, overdue collections; open, suspected, unknown,
  resolved; [docs/attention.md](docs/attention.md)); breadcrumbs and pipeline focus; the test
  investigation shows previous result, workflow, stability and two executions side by side;
  comparisons show count differences and their GitHub runs; copyable summaries in text and
  Markdown built by the server ([docs/m12-gap-analysis.md](docs/m12-gap-analysis.md)).
- **Actionable problems (UI)**: incomplete collections and failed refreshes link to where to
  look; collection problems link the pipeline and the GitHub run attempt; a Compare link to an
  unknown build explains instead of failing; layout regression tests at three widths.
- **Reliability and performance guards (M11, M14)**: `qi history check` reports a damaged file
  instead of crashing (found by a restore drill); killed imports, truncated downloads and expired
  artifacts covered by tests; the daily live check fails when the latest collection is older
  than 30 hours or collections keep coming in incomplete, and says what to do;
  `tools/benchmark.py`; performance guards on production-sized data in CI (structural and
  budgets); trends warmed too ([docs/performance.md](docs/performance.md)).
- **Production correctness (M9, M10)**, found on the live deployment:
  - the snapshot dropped 3 of 23 repositories and all but one file of multi-file jobs (jobs of
    the same name and context in different repositories replaced each other); it now keeps
    every repository and every file of a job's latest attempt (checked against SQL);
  - collected files without a timestamp take their CI run's start (schema 6 backfills);
  - a catalog `notice` says on every page that the sample requirements are synthetic;
  - `/api/health` and the footer name the deployed commit;
  - analyses are cached per snapshot and warmed before it goes live (overview 6.5 s live);
  - the collection audit reconciles the runs GitHub listed with the recorded attempts.
- **Requirement ownership (M6)**: `owner` on requirements (catalog TOML, CSV column), an Owner
  filter and facet, an owner column and matrix grouping; the sample requirements have synthetic
  team owners.
- **The whole portfolio is collected (M6)**: 23 repositories, 24 workflows, 59 jobs (was 4
  repositories); 16 repositories now publish JUnit XML as `junit-<job>` artifacts, 3 got CI;
  per-producer `since` keeps runs from before the contract out; every first run checked
  against its CI log ([docs/collection.md](docs/collection.md)).
- **TestNG retries in Surefire XML**: a retried attempt (written as a skipped test case) is a
  retry of the final result when the suite's `tests` count proves it; found in appium-framework's
  CI, where one flaky test showed as 40 passed + 1 skipped instead of 40 passed with a retry.
- **Hosted demonstration (M3)**: Docker image (pinned base, non-root, health check), Render
  blueprint deploying `main` after CI passed, `qi history fetch` (verified, atomic, ETag), the
  collection publishes the history as a release asset, JSON access log (`QI_ACCESS_LOG`),
  `tools/smoke.py`, CI job *Container image*, daily live check; [docs/deployment.md](docs/deployment.md).
  Fixed: `/api/status` counted no collections for fixed data.
- **Hosted operation (M5)**: login lock-out after 10 wrong logins (429), explicit public mode
  for public data (`QI_DASHBOARD_PUBLIC`), trusted proxies (`QI_FORWARDED_ALLOW_IPS`), HSTS over
  https, no-store API caching with a login; `qi history prune | backup | check | restore`;
  Dependabot; [docs/operations.md](docs/operations.md).
- **Accessibility and browsers**: axe-core WCAG 2.2 A/AA checks on every page in both themes
  (one finding fixed: 24 px targets in the run strips); theme and compact choice remembered;
  focus moves to the new page's heading; no sideways scrolling at 390/768/1280 px; browser tests
  in Chromium, Firefox and WebKit (found and fixed: date filters ignored in WebKit).
- **Tables, filters, charts**: sortable columns, row filter, CSV download (formula-safe),
  column chooser and paging on every table; Job filter, quick date ranges, removable filter
  chips, copy link to the view; trend bars are keyboard links to their day's runs; requirements
  matrix by criticality and feature with stale evidence; flaky candidates with the runs behind them.
- **Build comparison and test investigation**: Compare page (comparable suites only; newly
  failing, recovered, slower, newly flaky, coverage snapshots); test page with context, CI
  links, requirements, pass/fail pattern, duration chart, copy identifier and link.
- **Pipeline explorer and Collection page**: collected pipelines with status (incomplete before
  the CI conclusion), GitHub run and commit links, attempts, jobs with start times, status chips
  and workflow filter; collection health per repository with freshness and problems.
- **Repository selector**: repository identity on pipeline runs (schema 5), filter on every page.
- **Allure:** repeated TestNG invocations (`invocationCount`) are executions, not retries.

## 1.1.0 (2026-10-20)

- **Portfolio:** featured project 17 on https://niranjankagri.github.io with genuine dashboard screenshots.
- **Clean-checkout validation:** README steps run from fresh clones in cmd.exe and Git Bash
  ([docs/validation.md](docs/validation.md)); fixed the Git Bash activation line, documented the
  Windows long-path limit of the `e2e` extra; CI runs the tests and the demonstration on Windows too.
- **Requirements import from CSV** (`qi requirements import`): documented format (id, title,
  description, component, priority, criticality, risk, platforms), row-level errors, preview by
  default, all-or-nothing `--apply`, re-import without duplicates, hand-written files never
  overwritten, rollback when the catalog would break. Catalogs can `include` other files; the
  sample requirements now come from `samples/requirements.csv`. Requirements have an optional
  description, shown on the dashboard.
- **Trend analytics:** Trends page and `/api/trends`: results, pass rate, test duration and
  requirements by status per day (the snapshot at the end of each day), duration per run for each
  context, recorded coverage snapshots (`qi history import --catalog`, schema 2 with upgrade);
  days with new suites or carried-over runs are flagged; build and date-range filters everywhere;
  values checked against plain SQL on the stored records.
- **Cypress and Allure results:** mochawesome JSON or HTML reports and `allure-results` folders
  import into the same model as JUnit XML ([ADR 0005](docs/adr/0005-format-adapters.md)); Allure
  keys equal Surefire's JUnit keys; retries from repeated Allure `historyId`s; unknown statuses
  count as errors; unknown JSON makes a batch incomplete. Real samples in `samples/formats`:
  8 Cypress runs and 5 Allure runs, each Allure run checked test by test against the JUnit XML
  of the same CI job. `tools/sanitize_reports.py` cleans such reports for sharing.
- **Pipeline executions** ([docs/pipelines.md](docs/pipelines.md), [ADR 0006](docs/adr/0006-pipeline-executions.md)):
  `--pipeline ID --job NAME=PATH` (plus `--attempt`, `--branch`, `--commit`) on `qi gate` and
  `qi history import`; a gate file's `[pipeline] jobs` must all report, else the gate is
  incomplete (exit 3); a job's latest attempt counts; history refuses a second, different import
  of a job attempt (schema 3, upgraded on open); JSON/text/Markdown/HTML reports show the
  pipeline; Pipelines page and `/api/pipelines`. Real samples: a complete and a cancelled
  TaskBoard pipeline. The self gate now decides on its own CI run as a pipeline.
- **Security and reliability review** ([docs/security.md](docs/security.md)): hostile files are
  input errors (exit 3), never crashes: DTDs refused in any encoding (a UTF-16 file used to get
  its entities expanded), deep nesting and wrongly typed fields handled; size limits for catalog
  and gate files; the dashboard refuses non-local addresses without `QI_DASHBOARD_PASSWORD`, which
  turns on basic authentication; failure messages are redacted of secret-shaped values; Markdown
  summaries escape all Markdown punctuation; tests prove no imported content can be executed and
  the API takes no writes; CI audits dependencies with pip-audit; `SECURITY.md`.
- **CI maintenance** ([docs/ci.md](docs/ci.md)): `ubuntu-latest` had already moved to the
  ubuntu-26.04 image (verified in the job logs, all runs green); jobs now name `ubuntu-26.04` and
  `windows-2025`, with one test job left on `ubuntu-latest` as a canary for the next migration;
  actions are pinned to commit SHAs; a dependency audit job; 11 jobs in total.
- **Fixes found on the way:** two pipeline jobs in the same context (component and UI tests in
  Chrome) no longer replace each other in the snapshot; a late API response for an older address
  is no longer shown by the dashboard, and re-syncing the filters no longer overwrites the field
  being typed in (both races seen in CI); empty view slots no longer print "null".

**Upgrade notes**

- History databases are upgraded when opened (schema 1 or 2 to 3); existing runs are kept.
- `qi dashboard --host` with an address other than this machine now needs
  `QI_DASHBOARD_PASSWORD` (12+ characters), which turns on a login ([docs/security.md](docs/security.md)).
- A directory given as input is now also searched for `*.json` reports: a JSON file in it that
  is not a mochawesome report makes the import incomplete (exit 3). Point at the report folder,
  not at a whole project folder.
- The gate's JSON report has a new key, `pipeline` (`null` unless `--pipeline` is used); the
  other keys are unchanged.

## 1.0.0 (2026-10-20)

First complete release: all eight milestones of the project plan, each built and pushed in small
commits with CI.

- **Foundation:** package `qualityintel`, command `qi`, ruff (incl. docstrings), mypy `--strict`,
  pytest with branch coverage >= 90 % and warnings as errors, architecture test for the layering
  rule, GitHub Actions, decision records.
- **Data model:** typed, immutable requirements, test cases, links, runs and results; `Ratio`
  metrics that keep their counts and report n/a on a zero denominator; metric definitions.
- **Ingestion:** JUnit XML from pytest, Robot Framework, Maven Surefire/TestNG and Playwright Test,
  tested with 43 real CI result files; rerun elements, nested suites, explicit test ids, run context;
  every bad input reported, never ignored.
- **Traceability:** TOML catalog, result matching (explicit ids, `*`/`?` patterns), requirement,
  automation and automated-requirement coverage, gaps, breakdowns, execution status from the
  latest run per context; checked by hand counts and a second naive implementation.
- **Dashboard:** FastAPI JSON API and a static front end (overview, requirements, tests, runs,
  stability) with filters in the URL, drill-downs, empty and error states, strict CSP; tested in
  Chromium including phone width.
- **History:** SQLite store (lossless, idempotent, atomic); stability classes with evidence,
  recurring failures, duration regressions confirmed over two runs, trends, run comparison.
- **Quality gates:** TOML gate files; passed (0), failed (1), incomplete (3), internal error (4);
  missing or broken input never passes; JSON, HTML, Markdown and text reports.
- **Release:** reproducible demonstration (`tools/demo.py`), self-gate on the plan's acceptance
  criteria, repository hygiene test, diagrams, OpenAPI document, limitations.
