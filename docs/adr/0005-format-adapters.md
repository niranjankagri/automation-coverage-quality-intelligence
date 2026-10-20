# ADR 0005: Adapters for mochawesome and Allure results

Status: Accepted (2026-10-20)

## Context

[ADR 0002](0002-junit-xml-first.md) made JUnit XML the common format and allowed an adapter
when a framework does not write JUnit XML in practice. Two such cases are real here:

- the Cypress project's CI writes a mochawesome HTML report (with the JSON inside), not JUnit XML;
- the TestNG project's CI keeps `allure-results` as its main report; teams that publish Allure
  often have no JUnit XML at hand.

## Decision

Two importers, `ingest/mochawesome.py` and `ingest/allure.py`, produce the same `TestRun` /
`TestResult` model as the JUnit importer. Everything after ingestion (catalog matching,
history, gates, dashboard) is unchanged and does not know which format a run came from.

- **Supported input is defined narrowly**: mochawesome JSON or the HTML report carrying it;
  an `allure-results` folder of Allure 2 result files. Not a generated `allure-report/` site,
  whose data files are internal to Allure and change between versions.
- **Keys match JUnit where the formats allow it**: Allure's `testClass` + `testMethod` gives the
  same key as Surefire's JUnit XML, so history continues across a format switch.
- **Nothing is guessed silently**: unknown statuses become errors with a warning, unknown JSON
  is an error, fields the model has no place for are listed as "not read" in
  [ingestion.md](../ingestion.md).
- **Proof by real data**: each format has genuine CI samples, and the Allure runs are kept
  together with the JUnit XML of the same CI run, so a test compares both imports test by test.

## Consequences

- Cypress and Allure users import without changing their reporters.
- Information the formats lack stays missing (mochawesome: browser, build, retries) and is
  documented, not filled in.
- Data-driven rows are named differently by Allure and TestNG's JUnit XML; their history does
  not continue across formats (documented in limitations).
- A directory search now also reads `*.json`, so unrelated JSON files in a searched folder make
  the batch incomplete instead of being ignored. This is deliberate: a gate must not pass on a
  folder whose contents it could not read.
