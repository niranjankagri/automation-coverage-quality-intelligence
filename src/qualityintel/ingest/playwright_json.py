"""Playwright JSON importer: Playwright Test results with every retry attempt.

Supported input (docs/ingestion.md, "Playwright JSON"): the report of Playwright's ``json``
reporter (``--reporter=json`` or ``['json', { outputFile }]`` in the config), for one project.

Playwright's JUnit reporter writes a test that passed on a retry as plain passed, so flaky
Playwright tests are invisible there; this report keeps every attempt. One file is one run.
Mapping:

- one result per test of the file's project; the outcome is that of the last attempt:
  ``passed`` passed, ``failed`` and ``timedOut`` failed, ``skipped`` skipped,
  ``interrupted`` error; a test that never ran (no attempt) is skipped;
- ``retries`` = attempts before the last one, so a test that passed on a retry is a pass after
  retry (a flaky candidate), exactly like a Surefire rerun or a repeated Allure ``historyId``;
- key: the spec file (``file``, always with ``/``) + the describe titles and test title joined
  with U+203A (single right-pointing angle quotation mark) between spaces, which is what
  Playwright's JUnit reporter writes as classname and name, so the history of a test
  continues when a producer moves from JUnit to JSON;
- duration and start time of the last attempt; failure = its first error's message (colour
  codes removed) and stack;
- run start = ``stats.startTime``; run context: ``framework`` = ``playwright``; browser,
  environment and build are not in the report: give them with ``--context``;
- a file with results of several projects is refused: their tests share keys (write one
  report per project, as a CI job per browser does);
- not read: stdout, stderr, attachments, annotations, steps.
"""

from __future__ import annotations

import hashlib
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

STATUSES = {
    "passed": Outcome.PASSED,
    "failed": Outcome.FAILED,
    "timedOut": Outcome.FAILED,
    "skipped": Outcome.SKIPPED,
    "interrupted": Outcome.ERROR,
}
# Playwright's own separator between describe titles and the test title (JUnit name, list reporter)
TITLE_SEPARATOR = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def is_playwright_report(report: object) -> bool:
    """True for the top level of a Playwright JSON report (``config``, ``suites``, ``stats``)."""
    return (
        isinstance(report, dict)
        and isinstance(report.get("config"), dict)
        and isinstance(report.get("suites"), list)
        and isinstance(report.get("stats"), dict)
    )


def read_playwright_file(
    path: Path, context: RunContext | None = None, source: str | None = None
) -> ParsedFile:
    """Read a Playwright JSON report.

    Raises:
        MalformedResultError: Unreadable, too large, not valid JSON, several projects, or a test
            without a title.
        UnsupportedFormatError: Valid JSON that is not a Playwright report.
    """
    name = source or path.name
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            raise MalformedResultError(name, f"file is larger than the limit of {MAX_FILE_BYTES} bytes")
        data = path.read_bytes()
    except OSError as error:
        raise MalformedResultError(name, f"cannot be read ({error.strerror or error})") from None
    return parse_playwright(data, name, context)


def parse_playwright(data: bytes, source: str, context: RunContext | None = None) -> ParsedFile:
    """Parse Playwright JSON content; the run id is the SHA-256 of the report."""
    try:
        report = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError) as error:
        raise MalformedResultError(source, f"not valid JSON ({error})") from None
    except RecursionError as error:
        raise unexpected_structure(source, error) from None
    if not is_playwright_report(report):
        raise UnsupportedFormatError(
            source, "JSON without Playwright 'config', 'suites' and 'stats': not a Playwright report"
        )
    try:
        return _convert(report, data, source, context)
    except IngestError:
        raise
    except STRUCTURE_ERRORS as error:
        raise unexpected_structure(source, error) from None


def _convert(report: dict[str, Any], data: bytes, source: str, context: RunContext | None) -> ParsedFile:
    """A recognised Playwright report as a ParsedFile (fields of an unexpected type raise)."""
    tests = list(_tests(report["suites"]))
    projects = sorted({str(test.get("projectName") or "") for _, _, _, test in tests})
    if len(projects) > 1:
        raise MalformedResultError(
            source,
            f"results of several projects ({', '.join(p or '(unnamed)' for p in projects)}) in one "
            "file share their test keys; write one report per project",
        )
    results = [_result(file, titles, title, test, source) for file, titles, title, test in tests]
    warnings = [] if results else ["file contains no test cases"]
    run = TestRun(
        run_id=hashlib.sha256(data).hexdigest(),
        source=source,
        context=merge_context(RunContext(framework="playwright"), context),
        started_at=parse_timestamp(str(report["stats"].get("startTime") or "")),
        results=tuple(results),
    )
    return ParsedFile(run=run, warnings=tuple(warnings))


def _tests(suites: list[Any]) -> Iterator[tuple[str, list[str], str, Mapping[str, Any]]]:
    """Every test with its spec file, the describe titles around it and its own title."""

    def walk(
        suite: Mapping[str, Any], file: str, titles: list[str]
    ) -> Iterator[tuple[str, list[str], str, Mapping[str, Any]]]:
        for spec in suite.get("specs") or []:
            for test in spec.get("tests") or []:
                yield str(spec.get("file") or file), titles, str(spec.get("title") or "").strip(), test
        for child in suite.get("suites") or []:
            title = str(child.get("title") or "")
            yield from walk(child, str(child.get("file") or file), [*titles, title] if title else titles)

    for root in suites:
        if isinstance(root, dict):
            # the file suite's title is the path with the OS separator; ``file`` always uses "/"
            yield from walk(root, str(root.get("file") or root.get("title") or ""), [])


def _result(file: str, titles: list[str], title: str, test: Mapping[str, Any], source: str) -> TestResult:
    """One test of the report's project, decided by its last attempt."""
    if not title:
        raise MalformedResultError(source, f"a test in {file or 'an unnamed spec file'} has no title")
    attempts = [a for a in test.get("results") or [] if isinstance(a, dict)]
    last: Mapping[str, Any] = attempts[-1] if attempts else {}
    status = str(last.get("status") or "")
    # no attempt: the test was not run (e.g. after maxFailures); an unknown status is an error
    outcome = STATUSES.get(status, Outcome.ERROR) if attempts else Outcome.SKIPPED
    failure = None
    errors = [e for e in last.get("errors") or [] if isinstance(e, dict)] or (
        [last["error"]] if isinstance(last.get("error"), dict) else []
    )
    if outcome is not Outcome.PASSED and errors:
        message = _ANSI.sub("", str(errors[0].get("message") or "")).strip()
        failure = FailureDetails(
            message=message.splitlines()[0] if message else "",
            text=_ANSI.sub("", str(errors[0].get("stack") or message)).strip()[:MAX_FAILURE_TEXT],
        )
    duration = last.get("duration")
    return TestResult(
        name=TITLE_SEPARATOR.join([*titles, title]),
        classname=file,
        suite=titles[-1] if titles else file,
        outcome=outcome,
        duration_seconds=duration / 1000 if isinstance(duration, (int, float)) and duration >= 0 else None,
        timestamp=parse_timestamp(str(last.get("startTime") or "")),
        failure=failure,
        retries=max(len(attempts) - 1, 0),
    )
