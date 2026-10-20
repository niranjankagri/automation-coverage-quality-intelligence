# Automation Coverage & Quality Intelligence

[![CI](https://github.com/niranjankagri/automation-coverage-quality-intelligence/actions/workflows/ci.yml/badge.svg)](https://github.com/niranjankagri/automation-coverage-quality-intelligence/actions/workflows/ci.yml)

A quality engineering platform that sits **on top of** existing test automation frameworks. It
imports the results they already produce, links them to requirements, measures coverage,
tracks failures and flaky-test candidates over time, and decides configurable release
quality gates in CI.

It complements the Selenium, Playwright, Appium, Robot Framework and API automation projects in
my [portfolio](https://niranjankagri.github.io); it does not run tests itself and duplicates none
of them.

> **Status: in progress, see [Milestones](#milestones).** Nothing is claimed here before its
> milestone is done and tested.

## Goals

The questions a release decision needs, answered from data instead of opinion:

| Question | Answered by | Milestone |
|---|---|---|
| Which requirements have tests, and which of those are automated? | traceability | 4 |
| Which critical requirements have no coverage at all? | traceability | 4 |
| What happened in this run, per framework, environment and platform? | ingest + dashboard | 3, 5 |
| Which failures recur, which tests look flaky, which got slower? | history | 6 |
| Does this build meet the release criteria? | gates (exit code for CI) | 7 |

## Scope

**In scope:** JUnit XML results (first format), requirement-to-test mapping, coverage metrics
with documented formulas, SQLite history, JSON + HTML reports, CI quality gates, a lightweight
read-only dashboard, synthetic demonstration data.

**Out of scope:** running tests, replacing a framework's own report (screenshots, traces, videos
stay there), test management (writing test cases), multi-user hosting.

## Architecture

```
 requirements ─┐
               ▼
 JUnit XML ──> ingest ──> models ──> traceability ──> gates ──> JSON / HTML report, exit code
                  │                      ▲
                  ▼                      │
               history (SQLite) ─────────┘──> dashboard (read-only)
```

One Python package with one sub-package per responsibility. Business logic never depends on the
dashboard; a test parses every import and fails the build if it does. Details and reasons:
[docs/architecture.md](docs/architecture.md) and the decision records in [docs/adr](docs/adr/).

```
src/qualityintel/
  models/         typed data model (requirements, test cases, results)      M2
  ingest/         result files -> model, JUnit XML first                    M3
  traceability/   result matching, coverage metrics, gaps, execution status M4
  reporting/      text (and later JSON/HTML) renderers, no calculations
  dashboard/      FastAPI JSON API + static HTML/JS front end               M5
  workspace.py    view models behind every dashboard page (tested without a server)
  history/        SQLite history, trends, flaky-test candidates             M6
  gates/          release criteria, reports, pipeline exit status           M7
  config.py       settings from QI_* environment variables
  cli.py          the `qi` command
tests/
  unit/           one module at a time
  integration/    the installed package run as a separate process
  architecture/   layering rule checked on the source code
docs/
  architecture.md, adr/
```

## Dashboard

![Dashboard overview on the sample data](docs/images/dashboard-overview.png)

Read-only views of coverage, gaps, the latest runs, every test's history and every run, with
filters kept in the address and a JSON API documented at `/docs`. Details:
[docs/dashboard.md](docs/dashboard.md).

## Setup

Needs Python 3.12 or newer.

Windows (cmd.exe):

```bat
cd /d D:\path\to\automation-coverage-quality-intelligence
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,e2e]"
playwright install chromium
```

Linux / macOS:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,e2e]"
playwright install chromium   # only for the browser tests and screenshots
```

## Usage

```bash
qi version          # prints the version
qi config           # prints the settings in effect
qi inspect samples/results                       # what the result files contain
qi inspect "target/surefire-reports/TEST-*.xml"  # quoted patterns work in cmd.exe too
qi coverage --catalog samples/catalog.toml samples/results   # coverage, gaps, execution status
qi dashboard --catalog samples/catalog.toml samples/results  # web dashboard on http://127.0.0.1:8000
python -m qualityintel version   # same, when the qi script is not on PATH
```

Result files from pytest, Robot Framework, Maven Surefire/TestNG and Playwright Test are
imported and tested with real CI files ([docs/ingestion.md](docs/ingestion.md),
[samples/README.md](samples/README.md)). Requirements and their links to tests live in a TOML
catalog ([docs/traceability.md](docs/traceability.md)); metric formulas are in
[docs/metrics.md](docs/metrics.md).

Settings are optional environment variables, listed with their defaults in
[.env.example](.env.example). The tool needs no credentials.

Exit codes: `0` success, `2` wrong usage or invalid configuration, `3` input missing or invalid
(`1` = failed quality gate arrives in Milestone 7).

## Checks

The same commands run in CI ([.github/workflows/ci.yml](.github/workflows/ci.yml)):

```bash
ruff check .            # lint, including a docstring on every public item
ruff format --check .   # formatting
mypy                    # strict type checking of the package and the tests
pytest --cov            # tests; branch coverage below 90 % fails
pytest -m e2e           # dashboard in Chromium (needs `playwright install chromium`)
```

CI runs the static checks once, then the tests on Python 3.12 and 3.13 and the dashboard in
Chromium, and keeps the JUnit XML of each job (and the dashboard screenshots) as artifacts.

## Milestones

| # | Milestone | Status |
|---|---|---|
| 1 | Project foundation: package, tooling, CI, architecture | Done |
| 2 | Coverage data model and metric definitions | Done |
| 3 | Multi-framework result ingestion (JUnit XML) | Done |
| 4 | Requirement traceability engine | Done |
| 5 | Quality dashboard | Done |
| 6 | Historical quality intelligence | Planned |
| 7 | CI/CD quality gates | Planned |
| 8 | Portfolio-ready release | Planned |

A milestone is marked done only when its acceptance criteria pass.

## License

[MIT](LICENSE). All code and data in this repository are my own; the demonstration data is
synthetic.
