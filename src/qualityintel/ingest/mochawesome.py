"""Mochawesome importer: Cypress (and Mocha) results.

Supported input (docs/ingestion.md, "Cypress / mochawesome"):

- a mochawesome JSON report (``mochawesome``, ``mochawesome-merge``, or
  ``cypress-mochawesome-reporter`` with ``saveJson``), or
- a mochawesome HTML report, which carries the same JSON in the ``data-raw`` attribute of its
  body (what ``cypress-mochawesome-reporter`` writes by default).

One file is one run. Mapping:

- ``state`` passed / failed as they are; ``pending`` and ``skipped`` become skipped;
- key: the spec file (``fullFile``) + the test's full title (suite titles and test title);
- duration from milliseconds; failure = ``err.message`` and ``err.estack``;
- start time = ``stats.start``; run context: ``framework`` is ``cypress`` when a spec file name
  contains ``.cy.``, else ``mocha``; browser, environment and build are not in mochawesome
  reports: give them with ``--context``, or as a top-level ``qi_context`` object (this
  project's own convention, which mochawesome ignores);
- not read: ``code`` (test source), ``context`` (embedded screenshots and values), hooks.
  Cypress retries are not recorded by mochawesome, so ``retries`` stays 0.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from qualityintel.ingest.errors import (
    STRUCTURE_ERRORS,
    IngestError,
    MalformedResultError,
    UnsupportedFormatError,
    unexpected_structure,
)
from qualityintel.ingest.junit import MAX_FILE_BYTES, ParsedFile, merge_context, parse_timestamp
from qualityintel.models.enums import Outcome
from qualityintel.models.results import MAX_FAILURE_TEXT, FailureDetails, RunContext, TestResult, TestRun

STATES = {
    "passed": Outcome.PASSED,
    "failed": Outcome.FAILED,
    "pending": Outcome.SKIPPED,
    "skipped": Outcome.SKIPPED,
}
CONTEXT_FIELDS = frozenset({"framework", "environment", "browser", "platform", "build"})
_DATA_RAW = re.compile(rb'data-raw="([^"]*)"')


def read_mochawesome_file(
    path: Path, context: RunContext | None = None, source: str | None = None
) -> ParsedFile:
    """Read a mochawesome JSON or HTML report.

    Raises:
        MalformedResultError: Unreadable, too large, not valid JSON, or a test without a title.
        UnsupportedFormatError: Valid JSON or HTML that is not a mochawesome report.
    """
    name = source or path.name
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise MalformedResultError(name, f"file is larger than the limit of {MAX_FILE_BYTES} bytes")
        data = path.read_bytes()
    except OSError as error:
        raise MalformedResultError(name, f"cannot be read ({error.strerror or error})") from None
    return parse_mochawesome(data, name, context, html_report=path.suffix.lower() in {".html", ".htm"})


def parse_mochawesome(
    data: bytes, source: str, context: RunContext | None = None, html_report: bool = False
) -> ParsedFile:
    """Parse mochawesome content; the run id is the SHA-256 of the report JSON."""
    if html_report:
        found = _DATA_RAW.search(data)
        if found is None:
            raise UnsupportedFormatError(source, "HTML file without a mochawesome data-raw attribute")
        data = html.unescape(found.group(1).decode("utf-8", errors="replace")).encode()
    try:
        report = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MalformedResultError(source, f"not valid JSON ({error})") from None
    except RecursionError as error:
        raise unexpected_structure(source, error) from None
    if not isinstance(report, dict) or "stats" not in report or not isinstance(report.get("results"), list):
        raise UnsupportedFormatError(
            source, "JSON without mochawesome 'stats' and 'results': not a mochawesome report"
        )
    try:
        return _convert(report, data, source, context)
    except IngestError:
        raise
    except STRUCTURE_ERRORS as error:
        raise unexpected_structure(source, error) from None


def _convert(report: dict[str, Any], data: bytes, source: str, context: RunContext | None) -> ParsedFile:
    """A recognised mochawesome report as a ParsedFile (fields of an unexpected type raise)."""
    warnings: list[str] = []
    results = [_result(test, spec, titles, source) for spec, titles, test in _tests(report["results"])]
    if not results:
        warnings.append("file contains no test cases")
    stats = report.get("stats") or {}
    given = {k: str(v) for k, v in (report.get("qi_context") or {}).items() if k in CONTEXT_FIELDS and v}
    framework = "cypress" if any(".cy." in r.classname for r in results) else "mocha"
    file_context = RunContext.model_validate({"framework": framework, **given})
    run = TestRun(
        run_id=hashlib.sha256(data).hexdigest(),
        source=source,
        context=merge_context(file_context, context),
        started_at=parse_timestamp(str(stats.get("start") or "")),
        results=tuple(results),
    )
    return ParsedFile(run=run, warnings=tuple(warnings))


def _tests(results: list[Any]) -> Iterator[tuple[str, list[str], Mapping[str, Any]]]:
    """Every test with its spec file and the titles of the suites around it."""

    def walk(
        suite: Mapping[str, Any], spec: str, titles: list[str]
    ) -> Iterator[tuple[str, list[str], Mapping[str, Any]]]:
        title = str(suite.get("title") or "")
        here = [*titles, title] if title else titles
        for test in suite.get("tests") or []:
            yield spec, here, test
        for child in suite.get("suites") or []:
            yield from walk(child, spec, here)

    for root in results:
        if isinstance(root, dict):
            yield from walk(root, str(root.get("fullFile") or root.get("file") or ""), [])


def _result(test: Mapping[str, Any], spec: str, titles: list[str], source: str) -> TestResult:
    """One mochawesome test."""
    title = str(test.get("title") or "").strip()
    if not title:
        raise MalformedResultError(source, f"a test in {spec or 'an unnamed spec'} has no title")
    state = str(test.get("state") or ("pending" if test.get("pending") else ""))
    outcome = STATES.get(state)
    if outcome is None:
        # mochawesome writes state null for tests that never ran (e.g. after a failed hook)
        outcome = Outcome.SKIPPED if test.get("skipped") or test.get("pending") else Outcome.ERROR
    err = test.get("err") or {}
    failure = None
    if outcome is not Outcome.PASSED and (err.get("message") or err.get("estack")):
        failure = FailureDetails(
            message=str(err.get("message") or "").strip(),
            text=str(err.get("estack") or "").strip()[:MAX_FAILURE_TEXT],
        )
    duration = test.get("duration")
    return TestResult(
        name=" ".join([*titles, title]),
        classname=spec,
        suite=titles[-1] if titles else "",
        outcome=outcome,
        duration_seconds=duration / 1000 if isinstance(duration, (int, float)) and duration >= 0 else None,
        failure=failure,
    )
