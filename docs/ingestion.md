# Result ingestion

`qualityintel.ingest` turns result files into `TestRun` / `TestResult` objects
([models](../src/qualityintel/models/results.py)). JUnit XML is the main input format
([ADR 0002](adr/0002-junit-xml-first.md)); Cypress (mochawesome), Playwright JSON and Allure
results are read by adapters that produce the same model ([ADR 0005](adr/0005-format-adapters.md),
and [Other formats](#other-formats-cypress-playwright-json-and-allure) below).

| Input | Read as | Importer |
|---|---|---|
| `*.xml` file | JUnit XML | `ingest/junit.py` |
| `*.json` file with Playwright's `config`, `suites` and `stats` | Playwright JSON report | `ingest/playwright_json.py` |
| other `*.json` file | mochawesome JSON | `ingest/mochawesome.py` |
| `*.html` / `*.htm` file, named explicitly | mochawesome HTML report | `ingest/mochawesome.py` |
| folder that directly holds `*-result.json` files | one Allure run | `ingest/allure.py` |
| other folder | everything above found below it (HTML excepted) | `ingest/batch.py` |

## Tested producers

A producer is listed here only when real files from it are in `samples/results` and imported
by the integration tests.

| Producer | How to get JUnit XML | Tested with | Notes |
|---|---|---|---|
| pytest | `pytest --junitxml=reports/junit.xml` | 14 CI runs | `classname` = module path, parametrised ids stay in the name |
| Robot Framework | `robot --xunit xunit.xml` (or `rebot --xunit`) | 11 CI runs | nested suites; `classname` = dotted suite path |
| Maven Surefire + TestNG | `target/surefire-reports/TEST-TestSuite.xml` | 13 CI runs | no timestamp in the file; JVM properties are ignored |
| Playwright Test | `--reporter=junit`, or `npx playwright merge-reports --reporter junit <blob dir>` | 5 CI run attempts | `merge-reports` stamps the merge time, not the run time; a pass on a retry is written as a plain pass: use the [JSON report](#playwright-json) to see retries |

**No adapter was needed** for these four: their JUnit XML carries everything the model uses.
Cypress is read from its mochawesome report instead (next section).

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
| TestNG retry analyzer under Surefire: skipped `<testcase>` attempts before the final one of the same test | `TestResult.retries` of the final result, only when the suite's `tests` count equals the cases minus those attempts (otherwise kept as separate results) |
| `<testcase time>` | `duration_seconds`; missing = unknown; invalid (`abc`, negative, `1,234`) = unknown + warning |
| `<testsuite timestamp>` | earliest one = `TestRun.started_at`; no offset = UTC |
| testcase property `test_id` / `test_case_id`, `[TC-101]` in the name (upper-case prefix, so pytest ids like `[over-100]` do not count) | `TestResult.test_ids` (explicit link to a catalog test case) |
| suite properties `framework`, `browser`, `environment`/`env`, `platform`, `build`/`build_version` | `RunContext` (values given on the command line win) |

**Deliberately not read:** `<system-out>` and `<system-err>` (logs may contain secrets and are
large), all other properties (Surefire writes class paths and home directories), `hostname`.
Failure messages and texts pass through a redaction of secret-shaped values (tokens, passwords,
keys, credentials in URLs) in every format ([security.md](security.md)).
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
| DTD or entity declaration in the file, in any encoding | `UnsupportedFormatError` (JUnit XML never needs one; this rules out entity-expansion attacks) |
| Nesting deeper than Python can follow, fields of an unexpected type, an encoding the parser cannot read | `MalformedResultError` naming the file: an input problem (exit 3), never a crash ([security.md](security.md)) |
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

## Other formats: Cypress, Playwright JSON and Allure

Real samples: `samples/formats` ([what they are](../samples/README.md#formats-other-result-formats-real-ci-output)),
checked by `tests/integration/test_format_samples.py`.

### Cypress / mochawesome

Supported: the JSON that `mochawesome` or `mochawesome-merge` writes, and the HTML report of
`cypress-mochawesome-reporter`, which embeds the same JSON in its `data-raw` attribute.
Tested with Cypress 16.2 and cypress-mochawesome-reporter 5 (8 CI runs). One file = one run.

| mochawesome | Model |
|---|---|
| `results[].fullFile` (the spec file) | `classname` |
| suite titles + test `title` | `name` (so the key is `spec::Suite sub-suite test title`) |
| innermost suite title | `suite` |
| `state` passed / failed / pending / skipped | passed / failed / skipped / skipped |
| `state` null (never ran, e.g. after a failed hook) | skipped if marked `skipped`/`pending`, otherwise **error** |
| `duration` (ms) | `duration_seconds` |
| `err.message`, `err.estack` | `FailureDetails` |
| `stats.start` | `TestRun.started_at` |
| spec names with `.cy.` | `framework = cypress` (else `mocha`) |
| top-level `qi_context` object (this project's convention) | `RunContext`; values given on the command line win |

**Not available or not read:** mochawesome records no browser, environment or build (give them
with `--browser`/`--build`/... or record them as `qi_context`), and no retries (`retries` stays
0; Cypress retries are invisible here). Test source (`code`), `context` (screenshots, values)
and hooks are not read.

### Playwright JSON

Supported: the report of Playwright's `json` reporter (`--reporter=json`, or
`['json', { outputFile: 'test-results/results.json' }]` in `playwright.config.ts`), **one
project per file** (one CI job per browser writes exactly that). Tested with Playwright 1.64
(one CI run, four projects). One file = one run.

**Why it exists:** Playwright's JUnit reporter writes a test that passed on a retry as a plain
pass, so a flaky Playwright test is invisible in JUnit XML. In the sample run the checkout test
of the Chromium job failed once and passed on its retry: JUnit says *passed*, the JSON report
gives *passed after 1 retry*, which makes it a flaky candidate.

| Playwright JSON | Model |
|---|---|
| spec `file` (always with `/`; the file suite's title uses the OS separator) | `classname` |
| describe titles + spec `title`, joined with ` › ` | `name`: the **same key as Playwright's JUnit XML**, so history continues when a producer switches |
| innermost describe title (the file when there is none) | `suite` |
| the last attempt's `status`: passed / failed / timedOut / skipped / interrupted | passed / failed / failed / skipped / error (unknown: error) |
| attempts before the last one | `retries` (a pass with retries is a pass after retry) |
| a test without any attempt (e.g. after `maxFailures`) | skipped |
| the last attempt's first error: `message` (colour codes removed), `stack` | `FailureDetails` |
| the last attempt's `duration` (ms), `startTime` | `duration_seconds`, `timestamp` |
| `stats.startTime` | `TestRun.started_at` |
| (always) | `framework = playwright`; browser, environment and build come from `--browser`/`--build`/... or the producer's context |

**Not read:** stdout, stderr, attachments (screenshots, traces, videos), annotations, steps and
the earlier attempts' errors. A file with results of **several projects** is refused
(`MalformedResultError`): their tests share keys; write one report per project.

### Allure

Supported: an **`allure-results` folder** written by an Allure 2 adapter (TestNG, JUnit 5,
pytest, ...). Tested with the Allure TestNG adapter (5 CI runs). Not supported: a generated
`allure-report/` site, whose data files change between Allure versions.

| Allure result | Model |
|---|---|
| labels `testClass` + `testMethod` (else `fullName` split at the last dot) | `classname`, `name`: the **same key as the JUnit XML** of the same TestNG/JUnit test, so history continues when a team switches format |
| `parameters` values | appended to the name: `method[a, b]` |
| `status` passed / failed / skipped | the same |
| `status` broken | error |
| `status` unknown | error, with a warning |
| several results with the same `historyId` | one test; the latest is the outcome, the others are `retries` |
| `statusDetails.message`, `.trace` | `FailureDetails` |
| `stop - start` (ms) | `duration_seconds` |
| `AS_ID` labels, `tms` links | `test_ids` |
| `suite` label | `suite` |
| `framework` label | `RunContext.framework` |
| `environment.properties`: `browser`, `environment`; build = `build`, else `git.commit`, else `build.number` | `RunContext` |
| all result files | run id = SHA-256 over the file names and contents |

**Not read:** steps, attachments, `*-container.json` (fixtures), `categories.json`,
`executor.json`, `host`/`thread` labels (machine names), descriptions, other labels (`epic`,
`feature`, `tag`, ...) and `statusDetails.flaky` (flakiness is derived from history here).

**Data-driven tests differ between formats.** TestNG's JUnit XML names a data-provider row
`method[values in argument order](row number)`; Allure gives `method[values in its own
order]`. The same row therefore has different keys in the two formats, and its history does not
continue across a format switch. Plain test methods are not affected.

### Problems specific to these formats

| Situation | Result |
|---|---|
| JSON that is neither a Playwright nor a mochawesome report (`package.json`, `.last-run.json` ...) found in a directory | `UnsupportedFormatError`, batch incomplete: point the importer at the report, not the whole project folder |
| HTML without `data-raw` | `UnsupportedFormatError` (HTML is only read when named; a directory search skips it) |
| A test without a title; an Allure result without `name` or `status`; a Playwright report with several projects; invalid JSON | `MalformedResultError` naming the file |
| Allure folder larger than 50 MB in total | `MalformedResultError` |
| Same report or same Allure folder content twice | imported once, listed in `duplicates` |

**Gotcha:** a folder holding both `allure-results/` and `surefire-reports/` of the same run is
read as two runs, and every test counts twice in that context. Import one of them.

## Commands

```bash
qi inspect samples/results                          # every file below the folder
qi inspect "target/surefire-reports/TEST-*.xml"     # quoted: the importer expands the pattern
qi inspect junit.xml --framework pytest --build 1.4.2 --environment staging
qi inspect cypress/reports/index.html --browser chrome --build 1.4.2   # mochawesome HTML
qi inspect target/allure-results                    # one Allure run
```
