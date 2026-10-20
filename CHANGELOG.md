# Changelog

## Unreleased

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
