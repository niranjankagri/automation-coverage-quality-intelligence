import json
from pathlib import Path
from typing import Any

import pytest

from qualityintel.ingest.batch import read_any
from qualityintel.ingest.errors import MalformedResultError, UnsupportedFormatError
from qualityintel.ingest.junit import ParsedFile
from qualityintel.ingest.playwright_json import parse_playwright, read_playwright_file
from qualityintel.models.enums import Outcome
from qualityintel.models.results import RunContext

pytestmark = pytest.mark.unit

ARROW = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "


def attempt(status: str, retry: int = 0, message: str = "", **fields: Any) -> dict[str, Any]:
    """One attempt of a test, as Playwright's json reporter writes it."""
    errors = [{"message": message, "stack": f"{message}\n    at checkout.spec.ts:38:7"}] if message else []
    return {
        "workerIndex": 0,
        "status": status,
        "duration": 2500,
        "errors": errors,
        "stdout": [],
        "stderr": [],
        "retry": retry,
        "startTime": f"2026-10-26T06:32:{30 + retry:02d}.000Z",
        "attachments": [],
        **fields,
    }


def spec(title: str, *attempts: dict[str, Any], project: str = "chromium") -> dict[str, Any]:
    """A spec with one test of one project."""
    return {
        "title": title,
        "ok": True,
        "tags": [],
        "file": "ui/checkout.spec.ts",
        "tests": [{"projectName": project, "status": "expected", "results": list(attempts)}],
    }


def report(*specs: dict[str, Any], describe: str = "Checkout") -> dict[str, Any]:
    """A Playwright JSON report with one spec file and one describe block (Windows-style title)."""
    return {
        "config": {"version": "1.64.0", "projects": [{"name": "chromium"}]},
        "suites": [
            {
                "title": "ui\\checkout.spec.ts",
                "file": "ui/checkout.spec.ts",
                "specs": [],
                "suites": [{"title": describe, "file": "ui/checkout.spec.ts", "specs": list(specs)}],
            }
        ],
        "errors": [],
        "stats": {"startTime": "2026-10-26T06:32:26.685Z", "expected": 1, "flaky": 0},
    }


def parse(data: dict[str, Any], context: RunContext | None = None) -> ParsedFile:
    """Parse a report dict as results.json."""
    return parse_playwright(json.dumps(data).encode(), "results.json", context)


def test_a_pass_on_a_retry_is_a_pass_after_retry() -> None:
    """The case JUnit hides: failed once, passed on the retry -> passed, 1 retry (flaky candidate)."""
    run = parse(
        report(spec("orders two products", attempt("failed", 0, "Error: not found"), attempt("passed", 1)))
    ).run
    (result,) = run.results

    assert result.outcome is Outcome.PASSED
    assert result.retries == 1
    assert result.passed_after_retry
    assert result.failure is None
    assert result.duration_seconds == 2.5
    assert result.timestamp is not None
    assert result.timestamp.second == 31  # the last attempt


def test_key_equals_playwrights_junit_classname_and_name() -> None:
    """File with "/" (not the Windows suite title) :: describe titles and test title, as JUnit names them."""
    (result,) = parse(report(spec("orders two products", attempt("passed")))).run.results

    assert result.classname == "ui/checkout.spec.ts"
    assert result.name == f"Checkout{ARROW}orders two products"
    assert result.suite == "Checkout"


def test_nested_describes_are_all_in_the_name() -> None:
    """Every describe title is part of the name, outermost first."""
    data = report(describe="Checkout")
    data["suites"][0]["suites"][0]["suites"] = [
        {
            "title": "as a guest",
            "file": "ui/checkout.spec.ts",
            "specs": [spec("is asked to sign in", attempt("passed"))],
        }
    ]
    (result,) = parse(data).run.results

    assert result.name == f"Checkout{ARROW}as a guest{ARROW}is asked to sign in"


def test_a_test_outside_any_describe_is_named_by_its_title() -> None:
    """Without a describe block the name is the title and the suite is the file."""
    data = report()
    data["suites"][0]["specs"] = [spec("health check", attempt("passed"))]
    (result,) = parse(data).run.results

    assert (result.name, result.suite) == ("health check", "ui/checkout.spec.ts")


@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        ("passed", Outcome.PASSED),
        ("failed", Outcome.FAILED),
        ("timedOut", Outcome.FAILED),
        ("skipped", Outcome.SKIPPED),
        ("interrupted", Outcome.ERROR),
        ("something new", Outcome.ERROR),
    ],
)
def test_the_last_attempt_decides_the_outcome(status: str, outcome: Outcome) -> None:
    """Playwright's statuses mapped like JUnit's reporter does; an unknown status is never a pass."""
    (result,) = parse(report(spec("t", attempt(status)))).run.results

    assert result.outcome is outcome


def test_failed_after_all_retries_keeps_the_last_error_without_colour_codes() -> None:
    """Three attempts that all failed: failed with 2 retries; the message is the last attempt's first line."""
    red = "\x1b[31mError: expect(locator).toContainText(expected) failed\x1b[39m\n\nLocator: ..."
    (result,) = parse(
        report(
            spec(
                "t", attempt("failed", 0, "first"), attempt("failed", 1, "second"), attempt("failed", 2, red)
            )
        )
    ).run.results

    assert (result.outcome, result.retries) == (Outcome.FAILED, 2)
    assert result.failure is not None
    assert result.failure.message == "Error: expect(locator).toContainText(expected) failed"
    assert "\x1b" not in result.failure.text


def test_a_test_that_never_ran_is_skipped() -> None:
    """No attempt at all (e.g. stopped by maxFailures): skipped, not passed."""
    (result,) = parse(report(spec("t"))).run.results

    assert (result.outcome, result.retries) == (Outcome.SKIPPED, 0)


def test_run_has_start_time_framework_and_given_context() -> None:
    """stats.startTime is the run start; browser and build come from --context."""
    run = parse(report(spec("t", attempt("passed"))), RunContext(browser="chromium", build="6da9aba")).run

    assert run.started_at is not None
    assert run.started_at.isoformat().startswith("2026-10-26T06:32:26")
    assert (run.context.framework, run.context.browser, run.context.build) == (
        "playwright",
        "chromium",
        "6da9aba",
    )


def test_several_projects_in_one_file_are_refused() -> None:
    """Results of two projects would share keys: refused with the project names."""
    data = report(spec("t", attempt("passed")), spec("t", attempt("passed"), project="firefox"))

    with pytest.raises(MalformedResultError, match=r"several projects \(chromium, firefox\)"):
        parse(data)


@pytest.mark.parametrize(
    ("content", "error", "message"),
    [
        (b"{not json", MalformedResultError, "not valid JSON"),
        (b'{"stats": {}, "results": []}', UnsupportedFormatError, "not a Playwright report"),
        (b'{"config": {}, "suites": {}, "stats": {}}', UnsupportedFormatError, "not a Playwright report"),
        (b"[1, 2]", UnsupportedFormatError, "not a Playwright report"),
    ],
)
def test_bad_or_foreign_json_is_rejected(content: bytes, error: type[Exception], message: str) -> None:
    """Invalid or foreign JSON names the file and the reason."""
    with pytest.raises(error, match=f"^results.json: .*{message}"):
        parse_playwright(content, "results.json")


def test_wrongly_typed_fields_are_malformed_not_a_crash() -> None:
    """A results list that is not a list is a malformed file (exit 3), never an exception."""
    data = report(spec("t", attempt("passed")))
    data["suites"][0]["suites"][0]["specs"][0]["tests"][0]["results"] = 5

    with pytest.raises(MalformedResultError):
        parse(data)


def test_test_without_title_is_malformed() -> None:
    """A result that cannot be identified rejects the file."""
    with pytest.raises(MalformedResultError, match="has no title"):
        parse(report(spec("  ", attempt("passed"))))


def test_empty_report_gives_a_warning() -> None:
    """No tests: an empty run, and a warning saying so."""
    parsed = parse(report())

    assert parsed.run.results == ()
    assert parsed.warnings == ("file contains no test cases",)


def test_same_report_gives_the_same_run_id() -> None:
    """The run id is a content hash, so duplicate imports are detected."""
    data = json.dumps(report(spec("t", attempt("passed")))).encode()

    assert parse_playwright(data, "a.json").run.run_id == parse_playwright(data, "b.json").run.run_id


def test_read_from_file_names_the_source(tmp_path: Path) -> None:
    """read_playwright_file reads the bytes; the source defaults to the file name."""
    path = tmp_path / "results.json"
    path.write_text(json.dumps(report(spec("t", attempt("passed")))), encoding="utf-8")

    assert read_playwright_file(path).run.source == "results.json"


def test_batch_tells_playwright_and_mochawesome_json_apart(tmp_path: Path) -> None:
    """Both formats are *.json: the content decides the importer; anything else is named as neither."""
    playwright = tmp_path / "results.json"
    playwright.write_text(json.dumps(report(spec("t", attempt("passed")))), encoding="utf-8")
    mochawesome = tmp_path / "mochawesome.json"
    mochawesome.write_text(
        json.dumps({"stats": {"start": "2026-10-19T10:56:06Z"}, "results": []}), encoding="utf-8"
    )
    other = tmp_path / "package.json"
    other.write_text('{"name": "x"}', encoding="utf-8")

    assert read_any(playwright).run.context.framework == "playwright"
    assert read_any(mochawesome).run.context.framework == "mocha"
    with pytest.raises(UnsupportedFormatError, match="neither a Playwright nor a mochawesome report"):
        read_any(other)
