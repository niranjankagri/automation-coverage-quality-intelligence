# Execution history

The history turns many runs into answers that one run cannot give: which tests are flaky
candidates, which failures recur, which tests got slower, how each pipeline trends.

```bash
qi history import samples/results --catalog samples/catalog.toml   # store runs + a coverage snapshot
qi history report                          # stability, recurring failures, durations, trends
qi history compare 39229363499-attempt1.xml 39229363499-attempt3.xml
qi dashboard --catalog samples/catalog.toml --database .qi/quality.db   # Stability page
```

All rules and thresholds: [metrics.md, "History metrics"](metrics.md#history-metrics).

## Storage

SQLite through Python's standard `sqlite3` ([ADR 0003](adr/0003-sqlite-first.md)). The file is
`QI_DATABASE` (default `.qi/quality.db`) or `--database`.

| Table | Content |
|---|---|
| `runs` | run id (SHA-256 of the result file, primary key), source name, framework, environment, browser, platform, build, start time, import time; pipeline id, job, attempt, branch, commit when imported as part of a pipeline ([pipelines.md](pipelines.md)) |
| `results` | one row per result: name, classname, suite, outcome, duration, timestamp, failure message/type/text, explicit test ids, retries |
| `coverage_snapshots` | the catalog's three coverage metrics, recorded by `qi history import --catalog` when the catalog changed |
| `schema_version` | version of the layout (3); older files are upgraded when opened (new tables and columns are added, existing rows kept), a database written by a newer version is refused |

Properties, each with a test in `tests/unit/history/test_store.py`:

- **lossless:** every sample run read back from the database equals the imported run, field by
  field;
- **idempotent:** importing the same file again adds nothing (same run id);
- **atomic:** a run and its results are one transaction; a failed write leaves no half run;
- **all-or-nothing import:** `qi history import` stores nothing when any input file is broken,
  so a partial history never looks complete;
- **cascade delete:** removing a run removes its results.

One writer at a time. In CI, keep the database as an artifact or cache and run imports one after
the other; parallel jobs should write their own files.

**PostgreSQL: not added.** The plan allows it "only when there is a demonstrated need". So far
there is none: the sample history (43 runs, 2,345 results) loads in well under a second, and the
analysis code never touches SQL, so the store module is the only thing to replace if several
writers or a shared server ever require it.

## What the report shows on the sample data

```
STABILITY (per test and run context, last verdicts in the window)
  4 flaky candidate, 217 stable

FLAKY CANDIDATE (4)
  com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer
    testng/ci/firefox/linux · failure rate 10.0 % (1/10) · passed and failed on the same build (f5a40d5); 2 changes between pass and fail
  ui/catalog.spec.ts::Product catalogue › home page shows a full first page of products
    playwright/ci/firefox/linux · failure rate 20.0 % (1/5) · passed and failed on the same build (07f8c24); ...
  ...
DURATION REGRESSIONS (2)
  com.enterprise.automation.tests.ui.CustomerManagementTest::adminDeletesACustomer
    testng/ci/firefox/linux · 1.48 s -> 3.70 s (+151%, baseline of 10 runs)
  ...
```

These are real: every flaky candidate is a test that passed and failed on the same commit (the
13 Oct Firefox timeout of the enterprise nightly; the Playwright tests hit by the demo site's
outage during the three attempts of run 39229363499).

## Dashboard

The **Stability** page shows the class counts, every test that needs attention with its
evidence, recurring failures, duration regressions and a strip of runs per context (red = run
with failures). The window (5, 10, 20, 50 verdicts) is a control on the page; it is kept in the
address like the other filters.

![Stability page on the sample data](images/dashboard-stability.png)

## Comparing runs

`qi history compare BASE HEAD` takes a run id (at least 6 characters) or the end of a source
name. It prints newly failing, fixed, still failing, added, removed and clearly slower tests, and
warns when the two runs have different contexts.

## Comparing builds

`qualityintel/history/builds.py`, the dashboard's **Compare** page and `GET /api/compare?base=&head=`.

- A **build** is every run whose context names it (the commit or version tested); within a build
  the latest run per context and pipeline job counts, as in the snapshot.
- Two builds are compared **only where both ran the same suite** (same context and job). Those
  pairs go through the same comparison as `qi history compare`: newly failing, recovered, still
  failing, new and removed tests, and tests slower by the history thresholds (at least 50 % and
  0.5 s, [metrics.md](metrics.md)). Suites that ran in one build only are listed as such, never
  counted as new or removed tests.
- **Newly flaky:** flaky candidates in the history up to the comparison build's last run that
  were not flaky candidates up to the baseline's last run.
- **Coverage:** the latest coverage snapshot recorded before each build's last run; "no coverage
  snapshot before this build" when there is none.
- The build selectors list builds in the order they first ran; the page's build filter is
  ignored for the comparison (it chooses its builds itself).

On the sample data, TestNG on Firefox, builds `f5a40d5` → `1d03232`: one comparable suite and
10 tests slower; the 13 Oct timeout is not a change between builds because a later nightly on
the same commit passed (the latest run of a build counts), and the test's own history shows it.

## Latest regressions

`latest_regressions()` in `qualityintel/history/builds.py`, the top of the **Compare** page and
`GET /api/regressions` (M13). No builds are chosen: every suite is checked by itself.

- A **suite** is the comparison key of *Comparing builds* (run context, pipeline job and result
  file) **plus the pipeline branch**: a pull-request build is never the baseline of a `main`
  build.
- Only **dated runs with a build label** take part; an undated run cannot be placed before or
  after another. Per suite and build the **highest job attempt**, then the latest start, counts
  (a passing re-run replaces a failed first attempt).
- The suite's **newest build** is compared with the build that ran **just before it** in the same
  suite, with the same comparison as *Comparing runs*. Tests that passed there and fail or error
  now are the regression; recovered tests are shown beside them. A suite whose newest build has
  no new failure is counted as compared, not listed.
- Suites that ran in one build only are counted ("ran in one build only"), never treated as a
  regression or as passing.
- Each row links the two builds' comparison, both runs and every newly failing test.

