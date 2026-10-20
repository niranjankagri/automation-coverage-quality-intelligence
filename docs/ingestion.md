# Result ingestion

`qualityintel.ingest` turns result files into `TestRun` / `TestResult` objects
([models](../src/qualityintel/models/results.py)). JUnit XML is the only input format
([ADR 0002](adr/0002-junit-xml-first.md)).

## Tested producers

A producer is listed here only when real files from it are in `samples/results` and imported
by the integration tests.

| Producer | How to get JUnit XML | Tested with | Notes |
|---|---|---|---|
| pytest | `pytest --junitxml=reports/junit.xml` | 14 CI runs | `classname` = module path, parametrised ids stay in the name |
| Robot Framework | `robot --xunit xunit.xml` (or `rebot --xunit`) | 11 CI runs | nested suites; `classname` = dotted suite path |
| Maven Surefire + TestNG | `target/surefire-reports/TEST-TestSuite.xml` | 13 CI runs | no timestamp in the file; JVM properties are ignored |
| Playwright Test | `--reporter=junit`, or `npx playwright merge-reports --reporter junit <blob dir>` | 5 CI run attempts | `merge-reports` stamps the merge time, not the run time |

**No adapter was needed** for these four: their JUnit XML carries everything the model uses.
Cypress is not listed: the repository's CI writes mochawesome JSON. With
`cypress run --reporter junit` it would produce JUnit XML, but that has not been tested here.

Also covered by unit tests (inline XML): TestNG's `JUnitReportReporter` timestamp form
(`2026-10-19T07:36:12 UTC`), Surefire rerun elements (`flakyFailure`, `rerunFailure`),
namespaced elements.

## What is read

| JUnit XML | Model |
|---|---|
| `<testcase name>` | `TestResult.name` (required; a testcase without a name rejects the file) |
| `<testcase classname>` | `TestResult.classname` (may be empty) |
| innermost `<testsuite name>` | `TestResult.suite` |
| no child / `<failure>` / `<error>` / `<skipped>` | outcome `passed` / `failed` / `error` / `skipped`; several children: error > failure > skipped |
| `message`, `type`, body text of that child | `FailureDetails` (text cut to 4,000 characters, marked `... [truncated]`) |
| `<flakyFailure>`, `<flakyError>`, `<rerunFailure>`, `<rerunError>` | `TestResult.retries` (one per element) |
| `<testcase time>` | `duration_seconds`; missing = unknown; invalid (`abc`, negative, `1,234`) = unknown + warning |
| `<testsuite timestamp>` | earliest one = `TestRun.started_at`; no offset = UTC |
| testcase property `test_id` / `test_case_id`, `[TC-101]` in the name (upper-case prefix, so pytest ids like `[over-100]` do not count) | `TestResult.test_ids` (explicit link to a catalog test case) |
| suite properties `framework`, `browser`, `environment`/`env`, `platform`, `build`/`build_version` | `RunContext` (values given on the command line win) |

**Deliberately not read:** `<system-out>` and `<system-err>` (logs may contain secrets and are
large), all other properties (Surefire writes class paths and home directories), `hostname`.
The framework's own report stays the place for logs, screenshots and traces.

## Identity of a test

`key = classname::name` (or `name` alone when there is no classname). The key is what the
catalog's `automated_by` patterns match and what history uses to follow a test across runs.
Renaming a test or moving it to another class therefore starts a new history.

## Problems and how they are handled

| Situation | Result |
|---|---|
| File not found, pattern or directory matches nothing | `NoResultFilesError` |
| Empty file, not well-formed XML, testcase without a name, file > 50 MB | `MalformedResultError` (names the file; line and column for XML errors) |
| Well-formed XML that is not JUnit (`<testng-results>`, JSON ...) | `UnsupportedFormatError` |
| DTD or entity declaration in the file | `UnsupportedFormatError` (JUnit XML never needs one; this rules out entity-expansion attacks) |
| Same file content imported twice in one batch | imported once, listed in `duplicates` (run id = SHA-256 of the bytes) |
| Same test key twice in one file | both kept, warning |
| Suite with no test cases | empty run, warning |
| Unreadable suite timestamp or test time | value ignored, warning |

In a batch, one broken file does not stop the others, but the batch is marked **incomplete**
(`Batch.complete == False`) and `qi` exits with code 3. A quality gate never treats incomplete
input as success.

**Gotcha seen with real data:** `target/surefire-reports/` holds the same results several times
(`TEST-TestSuite.xml`, `junitreports/TEST-*.xml` per class, `testng-results.xml`). Importing the
whole directory would count each test twice; the per-class files differ in content, so duplicate
detection cannot catch it. Point the importer at `TEST-TestSuite.xml` only.

## Commands

```bash
qi inspect samples/results                          # every file below the folder
qi inspect "target/surefire-reports/TEST-*.xml"     # quoted: the importer expands the pattern
qi inspect junit.xml --framework pytest --build 1.4.2 --environment staging
```
