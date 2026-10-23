# Automation Coverage & Quality Intelligence

[![CI](https://github.com/niranjankagri/automation-coverage-quality-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/niranjankagri/automation-coverage-quality-intelligence/actions/workflows/ci.yml)

A quality engineering platform that sits **on top of** existing test automation. It imports the
results that Selenium/TestNG, Playwright, pytest, Robot Framework and Cypress suites already
produce (JUnit XML, mochawesome, Allure results), links them to requirements, and answers the questions a release decision needs:

- Which requirements are tested at all, and which of those tests are automated?
- Which **critical** requirements have no automated test?
- What failed in the latest runs, and which requirements does that put at risk?
- Which tests are **flaky candidates**, which failures recur, which tests got slower?
- Does this build meet the release criteria? (`qi gate` exits 0, 1 or 3 in CI)

**Business value:** coverage, pass rate and stability stop being opinions in a release meeting.
Every number is a documented formula with its counts (`90.5 % (38/42)`), every gap has a name
(`SHOP-008: card payment, planned, critical`), and the pipeline blocks a release on rules the team
wrote down, while broken or missing test results can never slip through as a pass.

**Live:** <https://quality-intelligence-0ur1.onrender.com>: the results the daily collection
gathers from the 23 test repositories of my portfolio (free hosting: the first visit after a
quiet spell takes about a minute to wake the service; [deployment](docs/deployment.md)).

It runs no tests and replaces no framework; it complements the automation projects in my
[portfolio](https://niranjankagri.github.io).

![Dashboard overview on the sample data](docs/images/dashboard-overview.png)

The overview includes a comparable-build change summary when the selected builds share suites.
The action center, collection freshness and repository evidence breakdown are documented with
sample screenshots in [the dashboard guide](docs/dashboard.md#screenshots-sample-data).

## Try it (about two minutes)

Python 3.12 or newer and Git. Nothing else: no database server, no configuration file, no
network access after the install.

Windows (cmd.exe):

```bat
git clone https://github.com/niranjankagri/automation-coverage-quality-intelligence.git
cd automation-coverage-quality-intelligence
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python tools\demo.py
qi dashboard --catalog samples/catalog.toml --database demo-output/quality.db
```

PowerShell: activate with `.venv\Scripts\Activate.ps1` (if scripts are blocked:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`). Git Bash: `source .venv/Scripts/activate`.
Linux / macOS: `python3 -m venv .venv` and `source .venv/bin/activate`; the other lines are the same.

`tools/demo.py` runs eleven documented steps and checks each exit code; it ends with
`11 of 11 steps behaved as documented`. The dashboard then runs on http://127.0.0.1:8000 (stop it
with Ctrl+C). These exact steps were run from a fresh clone on Windows (cmd, Git Bash) and run in
CI on Linux and Windows on every push: [docs/validation.md](docs/validation.md).

## What it does

| Area | Commands | What you get | Docs |
|---|---|---|---|
| Ingestion | `qi inspect` | JUnit XML, Cypress mochawesome reports and Allure results folders from files, folders or quoted patterns; outcomes, reruns, nested suites, explicit test ids, run context; every unreadable file reported | [ingestion](docs/ingestion.md) |
| Requirements | `qi requirements import` | CSV export (id, title, description, component, priority, criticality ...) into the catalog: preview, row-level errors, all-or-nothing, re-import without duplicates, test-case links preserved | [requirements import](docs/requirements-import.md) |
| Traceability | `qi coverage` | requirement coverage, automation coverage, automated requirement coverage; gaps; breakdowns by feature, criticality, test type, platform; execution status per requirement | [traceability](docs/traceability.md), [metrics](docs/metrics.md) |
| History | `qi history import / report / compare` | SQLite history with coverage snapshots; stability classes with evidence (flaky candidates, consistent and new failures); recurring failures; duration regressions; trends | [history](docs/history.md) |
| Quality gates | `qi gate` | configurable rules; passed / failed / incomplete as exit codes 0 / 1 / 3; JSON, HTML and Markdown reports | [quality gates](docs/quality-gates.md) |
| Collection | `qi collect` | the CI results of the whole portfolio (23 repositories, 59 jobs: TestNG, JUnit 5, Playwright, pytest, Cypress, Robot, Cucumber, Vitest, node:test, k6), fetched from their workflow artifacts every day: one pipeline execution per run attempt, idempotent, failed and cancelled runs kept apart, missing reports in a daily audit | [collection](docs/collection.md) |
| Pipelines | `--pipeline ID --job NAME=PATH` | the jobs of one CI execution grouped; re-run attempts; a gate never decides on a pipeline with a missing, empty or inconsistent job; Pipelines page | [pipelines](docs/pipelines.md) |
| Dashboard | `qi dashboard` | read-only web UI and JSON API (`/docs`) over the same numbers: readiness with definitions and evidence links; coverage by criticality, feature, owner and observed repository results; grouped navigation and collapsible URL-backed filters; responsive light/dark views; collection and snapshot health; accessible charts and tables; sortable and exportable data; WCAG 2.2 checks in three browser engines | [dashboard](docs/dashboard.md), [OpenAPI](docs/api/openapi.json) |
| Investigation | Search, Needs attention | search across tests, failure messages, requirements, pipelines and repositories; evidence-backed action groups and copy links; breadcrumbs and Back to filtered results; test history, failure details and deterministic copy summaries | [dashboard](docs/dashboard.md), [attention](docs/attention.md) |
| Operations | `qi history prune / backup / check / restore / fetch` | retention, verified backups and restores, a published history fetched safely; login lock-out, HSTS, JSON access log | [operations](docs/operations.md), [security](docs/security.md) |
| Hosting | `Dockerfile`, `render.yaml` | the public demonstration: a non-root image, deployed from `main` after CI passed, fed by the daily collection, smoke-tested daily | [deployment](docs/deployment.md) |

## The sample data is real

The 43 result files in [`samples/results`](samples/README.md) come from GitHub Actions runs of my
public test repositories (pytest, Robot Framework, Maven Surefire/TestNG with Selenium, Playwright
Test), sanitised before committing. They include real failures: a Selenium timeout in the
enterprise nightly of 13 Oct, and a Playwright run on 19 Oct that needed three attempts while the
public demo site was down. Only the requirements are synthetic: 42 requirements for the four demo applications those
repositories test, with deliberate gaps, kept as a CSV export
([`samples/requirements.csv`](samples/requirements.csv)) and imported into the catalog
([`samples/catalog.toml`](samples/catalog.toml) holds the hand-written test cases and links).

What the platform finds in it (each number checked by a test):

| Finding | Value |
|---|---|
| Requirement coverage / automation coverage / automated requirement coverage | 90.5 % (38/42) · 86.0 % (37/43) · 76.2 % (32/42) |
| Critical requirements without automation | `SHOP-008`, `ADMIN-012` → the sample release gate **fails** |
| Execution pass rate of the latest run per context | 100.0 % (221/221) → the nightly gate **passes** |
| Flaky candidates (passed and failed on the same build) | 4: the 13 Oct Selenium timeout and three Playwright tests hit by the site outage |
| Duration regressions confirmed over two runs | 2 (19 single-run spikes in a parallel suite were correctly ignored) |

More real CI output in [`samples/formats`](samples/README.md#formats-other-result-formats-real-ci-output)
and [`samples/pipelines`](samples/README.md#pipelines-whole-ci-pipeline-executions-real-ci-output):
8 Cypress runs, 5 Allure runs checked test by test against the JUnit XML of the same CI job, and
two whole Cypress pipeline runs. One of them was cancelled with its Firefox job missing: all 114
results that exist passed, and the pipeline gate still says **incomplete**.

![Pipelines page: the cancelled run is incomplete](docs/images/dashboard-pipelines.png)

## How it works

![Data flow](docs/images/data-flow.svg)

One Python package with one sub-package per responsibility; business logic never imports the
dashboard (a test parses every import to enforce it). Details: [architecture](docs/architecture.md),
[package layers](docs/images/architecture.svg), [decision records](docs/adr/).

```
src/qualityintel/
  models/         typed, immutable data model; Ratio keeps numerator and denominator
  ingest/         JUnit XML, mochawesome, Allure and catalog readers, batch import, errors that name the file
  traceability/   result matching, coverage metrics, gaps, execution status
  history/        SQLite store; stability, recurring failures, durations, trends
  gates/          gate file, rule evaluation, passed / failed / incomplete
  reporting/      text, JSON, HTML and Markdown renderers (no calculations)
  workspace.py    view models behind every dashboard page
  dashboard/      FastAPI JSON API + static HTML/JS front end
  cli.py          the qi command and its exit codes
```

## Quality gates in a pipeline

```yaml
- run: pytest --junitxml=reports/junit.xml
  continue-on-error: true
- if: always()                      # also when the tests crashed and wrote nothing
  run: >-
    qi gate --catalog quality/catalog.toml --config quality/release.toml reports/
    --context build=${{ github.sha }} --json reports/gate.json --html reports/gate.html
    --summary "$GITHUB_STEP_SUMMARY"
```

| Exit code | Meaning |
|---|---|
| 0 | every configured rule passed |
| 1 | a rule failed; the report names the requirements or tests |
| 2 | invalid gate file or usage (a misspelt threshold is an error, not a silently skipped rule) |
| 3 | input missing, unreadable or empty: **never** treated as a pass |
| 4 | internal error; a crash never looks like a gate decision |

![Release gate report](docs/images/gate-report-release.png)

## Evidence: the plan's acceptance criteria

This repository gates its own release on them: [`quality/catalog.toml`](quality/catalog.toml)
lists the ten acceptance criteria and five implementation rules of the project plan and the five
capabilities added after 1.0 (below), linked to their tests, and CI job *Self gate* runs `qi gate`
on this repository's own unit and browser results as one pipeline execution (20/20 requirements
automated, all tests passing).

| # | Criterion | Proven by |
|---|---|---|
| 1 | Results from at least two distinct automation projects import | 4 JUnit producers, 43 real files: `tests/integration/test_real_samples.py`; Cypress and Allure: `tests/integration/test_format_samples.py` |
| 2 | Normalised without losing essential information | counts equal each producer's own totals, context and failures survive (same file) |
| 3 | Requirements map to test cases | `tests/unit/traceability/test_matching.py`; every sample pattern matches a real test |
| 4 | Gaps and uncovered critical requirements are found | `tests/unit/traceability/test_coverage.py` (hand-calculated), sample hand counts |
| 5 | Dashboard metrics match independent calculations | a second, standard-library-only implementation in `tests/integration/test_sample_traceability.py`; API and browser tests show the same numbers |
| 6 | Historical trends can be inspected | `tests/unit/history/`, `qi history report`, the Stability page (browser test) |
| 7 | Gates pass or fail a pipeline | `tests/unit/test_cli_gate.py`; CI job *Quality gates* asserts exit codes 0, 1, 1 and 3 |
| 8 | Tests validate calculations, ingestion and gates | 765 unit and integration tests + 20 browser tests, 98 % branch coverage |
| 9 | A clean checkout reproduces the demonstration | `tests/integration/test_demo.py`; CI job *Demonstration from a clean checkout* |
| 10 | No sensitive data in docs and reports | `tests/integration/test_repository_hygiene.py` scans every tracked file (it found and fixed a local path in two sample files); failure messages are redacted ([security](docs/security.md)) |

Added after 1.0, each a requirement of the self gate:

| Id | Capability | Proven by |
|---|---|---|
| IMP-01 | Requirements import from CSV | `tests/unit/ingest/test_requirements_csv.py`, `tests/unit/test_cli_requirements.py`, the sample CSV |
| TREND-01 | Trend charts match the stored records | `tests/integration/test_trends_against_database.py` (plain SQL), browser tests |
| FMT-01 | Cypress (mochawesome) and Allure results | real samples; Allure and JUnit of the same CI run agree test by test |
| PIPE-01 | Pipeline executions: no decision on a pipeline with a missing job | a real cancelled pipeline: `tests/integration/test_pipeline_samples.py` |
| SEC-01 | Hostile input, dashboard login, no secrets in reports | `tests/unit/ingest/test_hostile_input.py`, `tests/architecture/test_no_code_execution.py`, [security](docs/security.md) |

## How this repository is checked

| Check | Tool | CI job |
|---|---|---|
| Lint incl. a docstring on every public item, formatting | ruff | Lint, format, types |
| Types, package and tests | mypy `--strict` | Lint, format, types |
| 765 unit and integration tests, branch coverage >= 90 % (98 %), warnings are errors | pytest | Tests (Python 3.12, 3.13 on Ubuntu 26.04; 3.13 on Windows and on the latest Ubuntu image) |
| 20 dashboard tests in a real browser, incl. 390 px phone width and a login | Playwright, Chromium | Dashboard in Chromium |
| Known vulnerabilities in installed dependencies | pip-audit | Dependency audit |
| Sample gates: passed, failed, failed on a real attempt, incomplete | `qi gate` | Quality gates (sample data) |
| The plan's acceptance criteria | `qi gate` on this repo's own results | Self gate |
| Reproducible demonstration | `tools/demo.py` | Demonstration from a clean checkout (Ubuntu and Windows) |

Runner images and actions are pinned ([CI](docs/ci.md)).

On Windows, the `e2e` extra (Playwright) installs files with very long paths: clone into a short
folder (for example `D:\src`) or enable Windows long paths, otherwise `pip` stops with
"No such file or directory". The basic install above is not affected.

Development setup: `pip install -e ".[dev,e2e]"`, `playwright install chromium`, then
`ruff check . && ruff format --check . && mypy && pytest --cov && pytest -m e2e`.

## Documentation

[Architecture](docs/architecture.md) · [Metric definitions](docs/metrics.md) ·
[Ingestion](docs/ingestion.md) · [Requirements import](docs/requirements-import.md) · [Traceability](docs/traceability.md) · [History](docs/history.md) · [Daily digest](docs/digest.md) ·
[Quality gates](docs/quality-gates.md) · [Pipelines](docs/pipelines.md) · [Collection](docs/collection.md) · [Dashboard and API](docs/dashboard.md) ·
[Security](docs/security.md) · [Operations](docs/operations.md) · [Deployment](docs/deployment.md) · [Performance](docs/performance.md) · [Limitations and future work](docs/limitations.md) · [Decision records](docs/adr/) ·
[Sample data](samples/README.md) · [Clean-checkout validation](docs/validation.md) · [Changelog](CHANGELOG.md)

## License

[MIT](LICENSE). Code, documentation and the requirement catalog are my own work; the sample
results are sanitised CI output of my own public repositories.
