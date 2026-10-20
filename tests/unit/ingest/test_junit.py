import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qualityintel.ingest.errors import MalformedResultError, UnsupportedFormatError
from qualityintel.ingest.junit import (
    MAX_FILE_BYTES,
    TRUNCATED,
    parse_junit,
    parse_timestamp,
    read_junit_file,
)
from qualityintel.models.enums import Outcome
from qualityintel.models.results import MAX_FAILURE_TEXT, FailureDetails, RunContext, TestResult

pytestmark = pytest.mark.unit


def parse(xml: str, context: RunContext | None = None) -> tuple[list[TestResult], list[str]]:
    """Parse inline XML; returns (results, warnings) for short assertions."""
    parsed = parse_junit(xml.encode(), source="inline.xml", context=context)
    return list(parsed.run.results), list(parsed.warnings)


def test_each_outcome_is_normalised() -> None:
    """No child = passed; failure, error and skipped map to their own outcome."""
    xml = """<testsuite name="s">
      <testcase classname="c" name="ok" time="0.5"/>
      <testcase classname="c" name="bad"><failure message="expected 2" type="AssertionError">trace</failure></testcase>
      <testcase classname="c" name="broken"><error message="boom" type="IOError"/></testcase>
      <testcase classname="c" name="later"><skipped message="not ready"/></testcase>
    </testsuite>"""

    results, _ = parse(xml)

    assert [(r.name, r.outcome) for r in results] == [
        ("ok", Outcome.PASSED),
        ("bad", Outcome.FAILED),
        ("broken", Outcome.ERROR),
        ("later", Outcome.SKIPPED),
    ]


def failure_of(result: TestResult) -> FailureDetails:
    """The failure details of a result that must have them."""
    assert result.failure is not None
    return result.failure


def test_failure_details_are_kept() -> None:
    """Message, type and the body text of a failure survive the import."""
    xml = """<testsuite name="s"><testcase classname="c" name="bad">
      <failure message=" expected [7] but found [6] " type="java.lang.AssertionError">  at Calc.test(Calc.java:12)  </failure>
    </testcase></testsuite>"""

    (result,), _ = parse(xml)

    assert failure_of(result).message == "expected [7] but found [6]"
    assert failure_of(result).type == "java.lang.AssertionError"
    assert failure_of(result).text == "at Calc.test(Calc.java:12)"


def test_long_failure_text_is_cut_with_a_marker() -> None:
    """Stack traces longer than the limit are cut, and the cut is visible."""
    xml = f'<testsuite name="s"><testcase name="t"><failure>{"x" * 10_000}</failure></testcase></testsuite>'

    (result,), _ = parse(xml)

    text = failure_of(result).text
    assert len(text) == MAX_FAILURE_TEXT
    assert text.endswith(TRUNCATED)


def test_worst_child_decides_when_there_are_several() -> None:
    """Error beats failure beats skipped, whatever the order in the file."""
    xml = """<testsuite name="s"><testcase name="t">
      <skipped/><failure message="f"/><error message="e"/><failure message="g"/>
    </testcase></testsuite>"""

    (result,), _ = parse(xml)

    assert result.outcome is Outcome.ERROR
    assert failure_of(result).message == "e"


def test_surefire_flaky_failure_means_passed_after_retry() -> None:
    """<flakyFailure> without a final failure: the test passed on a rerun."""
    xml = """<testsuite name="s"><testcase classname="c" name="t" time="3.1">
      <flakyFailure message="timeout" type="TimeoutException"/>
    </testcase></testsuite>"""

    (result,), _ = parse(xml)

    assert result.outcome is Outcome.PASSED
    assert result.retries == 1
    assert result.passed_after_retry


def test_surefire_rerun_failure_keeps_the_final_failure() -> None:
    """<rerunFailure> elements count as retries of a test that still failed."""
    xml = """<testsuite name="s"><testcase name="t">
      <failure message="first"/><rerunFailure message="second"/><rerunFailure message="third"/>
    </testcase></testsuite>"""

    (result,), _ = parse(xml)

    assert result.outcome is Outcome.FAILED
    assert result.retries == 2


def test_nested_suites_keep_the_innermost_suite_name() -> None:
    """Robot Framework nests suites; each result names the suite it sits in."""
    xml = """<testsuite name="Root"><testsuite name="Api">
      <testsuite name="01 Auth"><testcase classname="Root.Api.01 Auth" name="Login"/></testsuite>
    </testsuite><testcase name="top"/></testsuite>"""

    results, _ = parse(xml)

    assert [(r.name, r.suite) for r in results] == [("Login", "01 Auth"), ("top", "Root")]


def test_testsuites_root_and_namespaces_are_accepted() -> None:
    """<testsuites> root and namespaced elements are both JUnit XML."""
    xml = """<j:testsuites xmlns:j="urn:x"><j:testsuite name="s"><j:testcase name="t"/></j:testsuite></j:testsuites>"""

    results, _ = parse(xml)

    assert len(results) == 1


def test_missing_optional_fields_become_none_or_empty() -> None:
    """No classname, time or timestamp: allowed, recorded as unknown."""
    (result,), warnings = parse('<testsuite name="s"><testcase name="t"/></testsuite>')

    assert result.classname == ""
    assert result.duration_seconds is None
    assert result.timestamp is None
    assert warnings == []


@pytest.mark.parametrize("raw", ["abc", "-1", "nan", "inf", "1,234"])
def test_invalid_time_is_ignored_with_a_warning(raw: str) -> None:
    """A duration that cannot be a real execution time is dropped, not guessed."""
    (result,), warnings = parse(f'<testsuite name="s"><testcase name="t" time="{raw}"/></testsuite>')

    assert result.duration_seconds is None
    assert warnings == [f"testcase 't': invalid time {raw!r} ignored"]


def test_testcase_without_name_is_malformed() -> None:
    """A result that cannot be identified would be lost silently, so the file is rejected."""
    with pytest.raises(MalformedResultError, match=r"inline\.xml: testcase #2 in suite 's' has no name"):
        parse('<testsuite name="s"><testcase name="a"/><testcase classname="c" name=" "/></testsuite>')


def test_test_ids_come_from_properties_and_name_tokens() -> None:
    """Explicit ids: test_id property and [ID] tokens in the name, without duplicates."""
    xml = """<testsuite name="s"><testcase name="Login works [TC-101] [TC-102]">
      <properties><property name="test_id" value="TC-101"/><property name="owner" value="x"/></properties>
    </testcase><testcase name="HTTP-404 page"/></testsuite>"""

    results, _ = parse(xml)

    assert results[0].test_ids == ("TC-101", "TC-102")
    assert results[1].test_ids == ()


def test_context_comes_from_allow_listed_properties_only() -> None:
    """browser/environment are read; JVM properties with local paths are ignored."""
    xml = """<testsuite name="s"><properties>
        <property name="browser" value="firefox"/>
        <property name="env" value="staging"/>
        <property name="user.home" value="/home/someone"/>
        <property name="java.class.path" value="/secret/path.jar"/>
      </properties><testcase name="t"/></testsuite>"""

    parsed = parse_junit(xml.encode(), source="inline.xml")

    assert parsed.run.context == RunContext(browser="firefox", environment="staging")
    assert "/home/someone" not in parsed.run.model_dump_json()


def test_caller_context_wins_over_file_values() -> None:
    """Values given to the import command override what the file says."""
    xml = '<testsuite name="s"><properties><property name="browser" value="chrome"/></properties><testcase name="t"/></testsuite>'

    parsed = parse_junit(
        xml.encode(), source="x.xml", context=RunContext(browser="firefox", framework="robot")
    )

    assert parsed.run.context == RunContext(browser="firefox", framework="robot")


def test_run_id_is_the_content_hash_and_started_at_the_earliest_suite() -> None:
    """Same bytes = same run id; started_at is the earliest suite timestamp in UTC."""
    xml = """<testsuites>
      <testsuite name="b" timestamp="2026-10-19T12:00:00+02:00"><testcase name="t"/></testsuite>
      <testsuite name="a" timestamp="2026-10-19T09:30:00"><testcase name="u"/></testsuite>
    </testsuites>"""

    run = parse_junit(xml.encode(), source="x.xml").run

    assert run.run_id == hashlib.sha256(xml.encode()).hexdigest()
    assert run.started_at == datetime(2026, 10, 19, 9, 30, tzinfo=UTC)


def test_system_output_is_not_imported() -> None:
    """Logs may contain secrets; they stay in the framework's own report."""
    xml = """<testsuite name="s"><testcase name="t"><failure message="m">trace</failure>
      <system-out>password=hunter2</system-out><system-err>token=abc</system-err></testcase></testsuite>"""

    run = parse_junit(xml.encode(), source="x.xml").run

    assert "hunter2" not in run.model_dump_json()
    assert "token=abc" not in run.model_dump_json()


def test_duplicate_keys_in_one_file_give_a_warning() -> None:
    """Both results are kept; the warning tells the user why counts look higher."""
    xml = (
        '<testsuite name="s"><testcase classname="c" name="t"/><testcase classname="c" name="t"/></testsuite>'
    )

    results, warnings = parse(xml)

    assert len(results) == 2
    assert warnings == ["test 'c::t' appears 2 times in this file"]


def test_file_without_test_cases_gives_a_warning() -> None:
    """An empty suite imports as an empty run; the warning makes it visible."""
    results, warnings = parse('<testsuites><testsuite name="s" tests="0"/></testsuites>')

    assert results == []
    assert warnings == ["file contains no test cases"]


def test_unreadable_suite_timestamp_gives_a_warning() -> None:
    """A suite timestamp that cannot be parsed is ignored, not fatal."""
    _, warnings = parse('<testsuite name="s" timestamp="yesterday"><testcase name="t"/></testsuite>')

    assert warnings == ["suite 's': unreadable timestamp 'yesterday' ignored"]


@pytest.mark.parametrize(
    ("content", "error", "message"),
    [
        (b"", MalformedResultError, "file is empty"),
        (b"   \n", MalformedResultError, "file is empty"),
        (b"<testsuite><testcase name='t'>", MalformedResultError, r"not well-formed XML \(line 1"),
        (b"not xml at all", MalformedResultError, "not well-formed XML"),
        (b"<testng-results/>", UnsupportedFormatError, r"root element <testng-results> is not JUnit XML"),
        (b'{"tests": []}', MalformedResultError, "not well-formed XML"),
        (
            b'<!DOCTYPE x [<!ENTITY a "aaaa">]><testsuite name="&a;"/>',
            UnsupportedFormatError,
            "DTDs and entity declarations are not allowed",
        ),
    ],
    ids=["empty", "whitespace", "truncated", "text", "testng-native", "json", "dtd"],
)
def test_bad_files_are_rejected_with_the_file_name(
    content: bytes, error: type[Exception], message: str
) -> None:
    """Every rejection names the file and the reason."""
    with pytest.raises(error, match=f"^inline.xml: {message}"):
        parse_junit(content, source="inline.xml")


def test_read_from_disk_uses_only_the_file_name_as_source(tmp_path: Path) -> None:
    """Local directory names never end up in stored runs or reports."""
    path = tmp_path / "private" / "junit.xml"
    path.parent.mkdir()
    path.write_text('<testsuite name="s"><testcase name="t"/></testsuite>', encoding="utf-8")

    run = read_junit_file(path).run

    assert run.source == "junit.xml"


def test_missing_file_is_reported(tmp_path: Path) -> None:
    """A path that does not exist gives an import error, not an OSError traceback."""
    with pytest.raises(MalformedResultError, match=r"^gone\.xml: cannot be read"):
        read_junit_file(tmp_path / "gone.xml")


def test_oversized_content_is_rejected() -> None:
    """Content over the size limit is refused before parsing."""
    with pytest.raises(MalformedResultError, match="larger than the limit"):
        parse_junit(b" " * (MAX_FILE_BYTES + 1), source="big.xml")


def test_oversized_file_is_rejected_before_reading(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The size check on disk happens before the file is loaded into memory."""
    path = tmp_path / "big.xml"
    path.write_bytes(b"<testsuite/>")
    monkeypatch.setattr("qualityintel.ingest.junit.MAX_FILE_BYTES", 5)

    with pytest.raises(MalformedResultError, match=r"^big\.xml: file is 12 bytes, more than the limit of 5"):
        read_junit_file(path)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026-10-19T10:33:27.646611+00:00", datetime(2026, 10, 19, 10, 33, 27, 646611, tzinfo=UTC)),
        ("2026-10-19T10:33:27Z", datetime(2026, 10, 19, 10, 33, 27, tzinfo=UTC)),
        ("2026-10-19T12:33:27+02:00", datetime(2026, 10, 19, 10, 33, 27, tzinfo=UTC)),
        ("2026-10-19T11:07:55.569404", datetime(2026, 10, 19, 11, 7, 55, 569404, tzinfo=UTC)),
        ("2026-10-19T07:36:12 UTC", datetime(2026, 10, 19, 7, 36, 12, tzinfo=UTC)),
        ("", None),
        ("19/10/2026", None),
    ],
    ids=["pytest", "zulu", "offset", "robot-naive", "testng", "empty", "other"],
)
def test_timestamp_formats_seen_in_real_files(raw: str, expected: datetime | None) -> None:
    """Every producer's timestamp style ends up as an aware UTC datetime."""
    assert parse_timestamp(raw) == expected
