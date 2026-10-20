# Known limitations and future enhancements

What the platform does **not** do, and where its numbers can mislead. Each item says how it shows
up and what to do about it.

## Limitations

### Input

| Limitation | Effect | What to do |
|---|---|---|
| JUnit XML is the only input format | Cypress (mochawesome), Allure, TestNG's own `testng-results.xml` and Robot's `output.xml` cannot be read directly | use the framework's JUnit reporter (`--reporter junit`, `--xunit`, Surefire `TEST-*.xml`); write an adapter only if information would be lost |
| Supported producers are those with real sample files: pytest, Robot Framework, Maven Surefire/TestNG, Playwright Test | other producers probably work (same core format) but are not claimed | add a sample and a test before claiming support |
| `target/surefire-reports/` holds the same results several times | importing the whole folder counts tests twice (the files differ, so duplicate detection cannot help) | point at `TEST-TestSuite.xml` (or `TEST-*.xml` of one reporter) only |
| Logs, screenshots, traces are not imported | the dashboard shows failure messages and stack traces, nothing else | link to the framework's own report |
| Files up to 50 MB | larger files are refused | split the run |

### Identity and matching

| Limitation | Effect | What to do |
|---|---|---|
| A test is identified by `classname::name` | renaming or moving a test starts a new history; its test case shows "automated test case without results" and the new name shows as an unmatched result | update the `automated_by` pattern in the same change that renames the test (the gates' `max_automated_cases_without_results` rule catches the forgotten case) |
| Patterns are name-based | a too-wide pattern (`*`) can claim tests that do not verify the requirement | prefer explicit ids (`test_id` property, `[TC-101]` in the name) for important cases; review patterns like code |
| One result may belong to several test cases | it counts for each of them | intended; it is visible in the reports |

### Run context and the snapshot

| Limitation | Effect | What to do |
|---|---|---|
| The snapshot keeps the latest run per context (framework, environment, browser, platform) | two different suites with the same context (e.g. an API and a UI job that both record only `framework=pytest`) replace each other; only the newer one counts | record a distinguishing value: `--context browser=chromium`, a JUnit `browser`/`environment` property (this project's own e2e suite does this), or separate gate runs |
| Context comes only from the files and `--context` | files without timestamps sort before dated files; files without browser or environment share a context | add properties at the source, or sanitise with `--set` as the samples do |

### History metrics

| Limitation | Effect | What to do |
|---|---|---|
| Small samples | with 5 runs, one failure is 20 %; "stable after 3 runs" is weak evidence | read the counts next to every percentage; raise `min_verdicts` for stricter use |
| In-run retries are visible only when the producer records them | Surefire writes `flakyFailure`; pytest, Robot and Playwright's JUnit output do not | import each CI re-run attempt as its own file (the Playwright samples show how) |
| Durations in parallel suites depend on neighbours | single slow values are noise (seen in the 19 Oct TestNG sample) | duration regressions need two slow runs in a row; trust trends over single values |
| "Flaky candidate" is a hypothesis | it says the history looks intermittent, not why | investigate; all four sample candidates were caused by the environment |

### Storage and operation

| Limitation | Effect | What to do |
|---|---|---|
| SQLite, one writer at a time | concurrent CI jobs writing one file can block or fail | one import step after the test jobs, or one database per job |
| The dashboard loads data at start-up and is read-only, without authentication | new results need a restart; anyone who reaches the port can read everything | run it locally or behind the organisation's access control; do not expose it to the internet |
| Requirements live in a TOML file | no link to Jira, TargetProcess, Azure DevOps or Xray | export from the tool into the TOML format (a small script), or add an importer |

## Future enhancements

Not built, in the order they would add most value. None is claimed anywhere else in this repository.

1. **Requirement import** from a test-management tool (Jira/Xray, Azure DevOps, TargetProcess) into
   the catalog format, so the catalog stays in sync with the source of truth.
2. **Adapters** for Cypress mochawesome JSON and Allure results, each with real sample files.
3. **Run grouping by pipeline**, so a CI run with many jobs is one unit in history and gates.
4. **Live reload** in the dashboard when the history database changes.
5. **PostgreSQL** store, only if several writers or a shared server become a real need
   ([ADR 0003](adr/0003-sqlite-first.md)).
6. **Trend charts** (pass rate and duration over time) in the dashboard, next to the run strips.
7. **Ownership** (team or component per requirement) to route gaps and failures.
