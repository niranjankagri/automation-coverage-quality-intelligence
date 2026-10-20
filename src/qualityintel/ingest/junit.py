"""JUnit XML importer.

JUnit XML has no single official schema, so this module reads the common core and the
variants seen in real files (see docs/ingestion.md for the producers it is tested against):

- root ``<testsuites>`` or a single ``<testsuite>``; suites may be nested (Robot Framework);
- per ``<testcase>``: ``<failure>``, ``<error>`` or ``<skipped>`` child, or none = passed;
- Maven Surefire rerun elements: ``<flakyFailure>``/``<flakyError>`` (passed after a retry)
  and ``<rerunFailure>``/``<rerunError>`` (failed again on the retry);
- suite timestamps in ISO 8601 with or without offset, and TestNG's ``... UTC`` form.

What is deliberately *not* read: ``<system-out>``/``<system-err>`` (logs can hold secrets and
are large) and suite properties other than an allow-list (Surefire writes every JVM property,
including local paths and user names).
"""

from __future__ import annotations

import hashlib
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from qualityintel.ingest.errors import MalformedResultError, UnsupportedFormatError
from qualityintel.models.enums import Outcome
from qualityintel.models.results import MAX_FAILURE_TEXT, FailureDetails, RunContext, TestResult, TestRun

FORMAT = "junit-xml"
# Big enough for tens of thousands of results; larger files are almost certainly a mistake
MAX_FILE_BYTES = 50 * 1024 * 1024
# "Login works [TC-101]" -> TC-101. Brackets keep ids like "HTTP-404" in names from matching;
# the upper-case prefix keeps pytest parameter ids such as "[over-100]" from matching (found
# when this project gated its own test results)
DEFAULT_ID_PATTERN = re.compile(r"\[([A-Z][A-Z0-9]*-\d+)\]")
# Testcase properties that carry an explicit test case id
ID_PROPERTIES = frozenset({"test_id", "test_case_id", "testcase_id"})
# Suite properties copied into the run context (everything else is ignored, see module docstring)
CONTEXT_PROPERTIES = {
    "framework": "framework",
    "browser": "browser",
    "environment": "environment",
    "env": "environment",
    "platform": "platform",
    "build": "build",
    "build_version": "build",
}
TRUNCATED = "\n... [truncated]"

# Outcome precedence when one testcase has several result children
_SEVERITY = {Outcome.ERROR: 3, Outcome.FAILED: 2, Outcome.SKIPPED: 1, Outcome.PASSED: 0}
_FINAL_TAGS = {"failure": Outcome.FAILED, "error": Outcome.ERROR, "skipped": Outcome.SKIPPED}
_RETRY_TAGS = frozenset({"flakyFailure", "flakyError", "rerunFailure", "rerunError"})


@dataclass(frozen=True)
class ParsedFile:
    """A parsed result file and anything worth telling the user about it."""

    run: TestRun
    warnings: tuple[str, ...]


def read_junit_file(
    path: Path,
    context: RunContext | None = None,
    id_pattern: re.Pattern[str] = DEFAULT_ID_PATTERN,
    source: str | None = None,
) -> ParsedFile:
    """Read one JUnit XML file from disk.

    Args:
        path: The result file.
        context: Run context given by the caller; its values win over values found in the file.
        id_pattern: Pattern whose first group extracts a test case id from a test name.
        source: Name to record for the run; the file name when omitted. Never an absolute
            path, so local directory names stay out of stored runs and reports.

    Raises:
        MalformedResultError: Unreadable, empty, too large or not well-formed.
        UnsupportedFormatError: Well-formed XML that is not JUnit XML.
    """
    source = source or path.name
    try:
        size = path.stat().st_size
        if size > MAX_FILE_BYTES:
            raise MalformedResultError(
                source, f"file is {size} bytes, more than the limit of {MAX_FILE_BYTES}"
            )
        data = path.read_bytes()
    except OSError as error:
        raise MalformedResultError(source, f"cannot be read ({error.strerror or error})") from None
    return parse_junit(data, source=source, context=context, id_pattern=id_pattern)


def parse_junit(
    data: bytes,
    source: str,
    context: RunContext | None = None,
    id_pattern: re.Pattern[str] = DEFAULT_ID_PATTERN,
) -> ParsedFile:
    """Parse JUnit XML content into a :class:`TestRun`.

    The run id is the SHA-256 of the exact bytes, so the same file imported twice is detected
    later, while a re-run that produced a new file is a new run.

    Raises:
        MalformedResultError: Empty, not well-formed, or a testcase without a name.
        UnsupportedFormatError: Contains a DTD, or the root element is not a JUnit suite.
    """
    if len(data) > MAX_FILE_BYTES:
        raise MalformedResultError(source, f"content is larger than the limit of {MAX_FILE_BYTES} bytes")
    if not data.strip():
        raise MalformedResultError(source, "file is empty")
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        # JUnit XML never needs a DTD; refusing it rules out entity-expansion attacks
        raise UnsupportedFormatError(source, "DTDs and entity declarations are not allowed in result files")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as error:
        line, column = error.position
        raise MalformedResultError(source, f"not well-formed XML (line {line}, column {column})") from None

    root_tag = _local(root.tag)
    if root_tag not in {"testsuites", "testsuite"}:
        raise UnsupportedFormatError(
            source, f"root element <{root_tag}> is not JUnit XML (expected <testsuites> or <testsuite>)"
        )

    collector = _Collector(source, id_pattern)
    collector.walk(root, suite_name=root.get("name", "") if root_tag == "testsuite" else "")
    if not collector.results:
        collector.warnings.append("file contains no test cases")

    file_context = RunContext.model_validate(collector.context_values)
    merged = merge_context(file_context, context)
    run = TestRun(
        run_id=hashlib.sha256(data).hexdigest(),
        source=source,
        context=merged,
        started_at=min(collector.timestamps, default=None),
        results=tuple(collector.results),
    )
    collector.warn_about_duplicate_keys(run.results)
    return ParsedFile(run=run, warnings=tuple(collector.warnings))


class _Collector:
    """Walks the element tree once and gathers results, context values and warnings."""

    def __init__(self, source: str, id_pattern: re.Pattern[str]) -> None:
        self.source = source
        self.id_pattern = id_pattern
        self.results: list[TestResult] = []
        self.warnings: list[str] = []
        self.timestamps: list[datetime] = []
        self.context_values: dict[str, str] = {}

    def walk(self, element: ET.Element, suite_name: str) -> None:
        """Visit a suite element: read its timestamp and properties, then its children."""
        if _local(element.tag) == "testsuite":
            self._read_suite_attributes(element)
        for child in element:
            tag = _local(child.tag)
            if tag == "testsuite":
                self.walk(child, suite_name=child.get("name", ""))
            elif tag == "testcase":
                self.results.append(self._read_testcase(child, suite_name))

    def _read_suite_attributes(self, suite: ET.Element) -> None:
        """Collect the suite timestamp and allow-listed properties."""
        raw = suite.get("timestamp")
        if raw:
            parsed = parse_timestamp(raw)
            if parsed is None:
                self.warnings.append(
                    f"suite {suite.get('name', '?')!r}: unreadable timestamp {raw!r} ignored"
                )
            else:
                self.timestamps.append(parsed)
        for name, value in _properties(suite):
            field = CONTEXT_PROPERTIES.get(name.lower())
            if field and value and field not in self.context_values:
                self.context_values[field] = value

    def _read_testcase(self, case: ET.Element, suite_name: str) -> TestResult:
        """Turn one ``<testcase>`` into a :class:`TestResult`."""
        name = (case.get("name") or "").strip()
        if not name:
            raise MalformedResultError(
                self.source, f"testcase #{len(self.results) + 1} in suite {suite_name!r} has no name"
            )
        classname = (case.get("classname") or "").strip()

        outcome = Outcome.PASSED
        detail: ET.Element | None = None
        retries = 0
        for child in case:
            tag = _local(child.tag)
            if tag in _RETRY_TAGS:
                retries += 1
            elif tag in _FINAL_TAGS and _SEVERITY[_FINAL_TAGS[tag]] > _SEVERITY[outcome]:
                outcome = _FINAL_TAGS[tag]
                detail = child

        explicit_ids = [value for key, value in _properties(case) if key.lower() in ID_PROPERTIES and value]
        explicit_ids += self.id_pattern.findall(name)

        return TestResult(
            name=name,
            classname=classname,
            suite=suite_name,
            outcome=outcome,
            duration_seconds=self._duration(case, name),
            timestamp=parse_timestamp(case.get("timestamp") or ""),
            failure=_failure_details(detail) if detail is not None else None,
            test_ids=tuple(dict.fromkeys(explicit_ids)),  # unique, order kept
            retries=retries,
        )

    def _duration(self, case: ET.Element, name: str) -> float | None:
        """Read ``time`` in seconds; missing = unknown, invalid = unknown with a warning."""
        raw = case.get("time")
        if raw is None or raw.strip() == "":
            return None
        try:
            value = float(raw)
        except ValueError:
            # "1,234" could mean 1.234 s (decimal comma) or 1234 s: do not guess
            value = -1.0
        if value < 0 or not math.isfinite(value):
            self.warnings.append(f"testcase {name!r}: invalid time {raw!r} ignored")
            return None
        return value

    def warn_about_duplicate_keys(self, results: tuple[TestResult, ...]) -> None:
        """The same key twice in one file is legal (e.g. a re-run) but worth pointing out."""
        seen: dict[str, int] = {}
        for result in results:
            seen[result.key] = seen.get(result.key, 0) + 1
        for key, count in seen.items():
            if count > 1:
                self.warnings.append(f"test {key!r} appears {count} times in this file")


def parse_timestamp(raw: str) -> datetime | None:
    """Parse a JUnit timestamp; values without an offset are taken as UTC.

    Accepts ISO 8601 (``2026-10-19T10:33:27.646611+00:00``, ``...Z``, no offset) and the form
    TestNG writes (``2026-10-19T07:36:12 UTC``). Returns ``None`` for anything else.
    """
    text = raw.strip()
    if not text:
        return None
    if text.endswith(" UTC"):
        text = text[: -len(" UTC")]
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def _failure_details(element: ET.Element) -> FailureDetails:
    """Message, type and (cut) body text of a failure, error or skipped element."""
    text = (element.text or "").strip()
    if len(text) > MAX_FAILURE_TEXT:
        text = text[: MAX_FAILURE_TEXT - len(TRUNCATED)] + TRUNCATED
    return FailureDetails(
        message=(element.get("message") or "").strip(),
        type=(element.get("type") or "").strip(),
        text=text,
    )


def _properties(element: ET.Element) -> list[tuple[str, str]]:
    """``(name, value)`` pairs of the element's own ``<properties>`` block."""
    pairs: list[tuple[str, str]] = []
    for block in element:
        if _local(block.tag) != "properties":
            continue
        for prop in block:
            if _local(prop.tag) == "property" and prop.get("name"):
                value = prop.get("value")
                pairs.append(
                    (prop.get("name", ""), (value if value is not None else prop.text or "").strip())
                )
    return pairs


def merge_context(from_file: RunContext, given: RunContext | None) -> RunContext:
    """Caller-given values win; file values fill the gaps."""
    if given is None:
        return from_file
    merged = from_file.model_dump() | {k: v for k, v in given.model_dump().items() if v is not None}
    return RunContext.model_validate(merged)


def _local(tag: str) -> str:
    """Element name without an XML namespace (``{ns}testsuite`` -> ``testsuite``)."""
    return tag.rsplit("}", 1)[-1]
