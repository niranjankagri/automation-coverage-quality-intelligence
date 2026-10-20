import html
import json
from pathlib import Path
from typing import Any

import pytest

from qualityintel.ingest.errors import MalformedResultError, UnsupportedFormatError
from qualityintel.ingest.mochawesome import parse_mochawesome, read_mochawesome_file
from qualityintel.models.enums import Outcome
from qualityintel.models.results import RunContext

pytestmark = pytest.mark.unit


def case(title: str, state: str | None, **fields: Any) -> dict[str, Any]:
    """A mochawesome test entry."""
    return {
        "title": title,
        "fullTitle": title,
        "state": state,
        "duration": 1500,
        "err": {},
        "code": "cy.visit()",
        "context": None,
        **fields,
    }


def report(*suites: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """A mochawesome report with one root per spec file."""
    return {
        "stats": {"tests": 0, "start": "2026-10-19T10:56:06.338Z"},
        "results": [
            {
                "title": "",
                "fullFile": "cypress/e2e/ui/tasks.cy.ts",
                "file": "cypress/e2e/ui/tasks.cy.ts",
                "tests": [],
                "suites": list(suites),
            }
        ],
        "meta": {},
        **extra,
    }


SUITE = {
    "title": "Tasks",
    "tests": [
        case("creates a task", "passed"),
        case(
            "deletes a task",
            "failed",
            err={
                "message": "AssertionError: expected 2 to equal 1",
                "estack": "at Context.<anonymous> (tasks.cy.ts:12:5)",
            },
        ),
        case("exports tasks", "pending"),
    ],
    "suites": [{"title": "when offline", "tests": [case("shows a banner", "skipped")], "suites": []}],
}


def parse(data: dict[str, Any], **kwargs: Any) -> Any:
    """Parse a report dict."""
    return parse_mochawesome(json.dumps(data).encode(), "report.json", **kwargs)


def test_states_titles_and_failures_are_mapped() -> None:
    """passed/failed as they are, pending and skipped as skipped; nested suite titles in the name."""
    run = parse(report(SUITE)).run

    assert [(r.name, r.outcome) for r in run.results] == [
        ("Tasks creates a task", Outcome.PASSED),
        ("Tasks deletes a task", Outcome.FAILED),
        ("Tasks exports tasks", Outcome.SKIPPED),
        ("Tasks when offline shows a banner", Outcome.SKIPPED),
    ]
    failed = run.results[1]
    assert failed.classname == "cypress/e2e/ui/tasks.cy.ts"
    assert failed.key == "cypress/e2e/ui/tasks.cy.ts::Tasks deletes a task"
    assert failed.duration_seconds == 1.5
    assert failed.failure is not None
    assert failed.failure.message == "AssertionError: expected 2 to equal 1"
    assert "tasks.cy.ts:12:5" in failed.failure.text
    assert run.started_at is not None
    assert run.started_at.isoformat() == "2026-10-19T10:56:06.338000+00:00"


def test_framework_is_detected_and_context_can_be_recorded() -> None:
    """.cy. spec files mean Cypress; qi_context fills what mochawesome cannot know; --context wins."""
    plain = parse(report(SUITE)).run
    recorded = parse(report(SUITE, qi_context={"browser": "chrome", "build": "abc", "owner": "x"})).run
    overridden = parse(
        report(SUITE, qi_context={"browser": "chrome"}), context=RunContext(browser="firefox")
    ).run

    assert plain.context == RunContext(framework="cypress")
    assert recorded.context == RunContext(
        framework="cypress", browser="chrome", build="abc"
    )  # unknown keys ignored
    assert overridden.context.browser == "firefox"
    mocha = report(SUITE)
    mocha["results"][0]["fullFile"] = "test/tasks.spec.js"
    assert parse(mocha).run.context.framework == "mocha"


def test_a_test_that_never_ran_is_not_counted_as_passed() -> None:
    """State null (e.g. after a failed before-hook): skipped if flagged so, otherwise an error."""
    run = parse(
        report({"title": "S", "tests": [case("a", None, skipped=True), case("b", None)], "suites": []})
    ).run

    assert [r.outcome for r in run.results] == [Outcome.SKIPPED, Outcome.ERROR]


def test_html_report_is_read_from_its_data_raw_attribute(tmp_path: Path) -> None:
    """cypress-mochawesome-reporter's default HTML carries the JSON; both give the same results."""
    data = json.dumps(report(SUITE))
    page = tmp_path / "index.html"
    page.write_text(
        f'<html><body data-raw="{html.escape(data, quote=True)}"><script>x</script></body></html>',
        encoding="utf-8",
    )
    as_json = tmp_path / "report.json"
    as_json.write_text(data, encoding="utf-8")

    assert read_mochawesome_file(page).run.results == read_mochawesome_file(as_json).run.results


@pytest.mark.parametrize(
    ("content", "error", "message"),
    [
        (b"{not json", MalformedResultError, "not valid JSON"),
        (b'{"tests": []}', UnsupportedFormatError, "not a mochawesome report"),
        (b"[1, 2]", UnsupportedFormatError, "not a mochawesome report"),
    ],
)
def test_bad_json_is_rejected(content: bytes, error: type[Exception], message: str) -> None:
    """Invalid or foreign JSON names the file and the reason."""
    with pytest.raises(error, match=f"^report.json: .*{message}"):
        parse_mochawesome(content, "report.json")


def test_html_without_report_data_is_unsupported() -> None:
    """A random HTML page is not taken for a report."""
    with pytest.raises(UnsupportedFormatError, match="without a mochawesome data-raw attribute"):
        parse_mochawesome(b"<html><body>hello</body></html>", "page.html", html_report=True)


def test_test_without_title_is_malformed() -> None:
    """A result that cannot be identified rejects the file."""
    with pytest.raises(MalformedResultError, match="has no title"):
        parse(report({"title": "S", "tests": [case("", "passed")], "suites": []}))


def test_empty_report_gives_a_warning() -> None:
    """No tests: an empty run, and a warning saying so."""
    parsed = parse(report())

    assert parsed.run.results == ()
    assert parsed.warnings == ("file contains no test cases",)


def test_same_report_gives_the_same_run_id() -> None:
    """The run id is a content hash, so duplicate imports are detected."""
    data = json.dumps(report(SUITE)).encode()

    assert parse_mochawesome(data, "a.json").run.run_id == parse_mochawesome(data, "b.json").run.run_id
