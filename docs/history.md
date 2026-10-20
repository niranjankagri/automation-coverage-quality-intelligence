# Execution history

The history turns many runs into answers that one run cannot give: which tests are flaky
candidates, which failures recur, which tests got slower, how each pipeline trends.

```bash
qi history import samples/results          # store runs (default database: .qi/quality.db)
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
| `runs` | run id (SHA-256 of the result file, primary key), source name, framework, environment, browser, platform, build, start time, import time |
| `results` | one row per result: name, classname, suite, outcome, duration, timestamp, failure message/type/text, explicit test ids, retries |
| `schema_version` | version of the layout; a database written by a newer version is refused |

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
