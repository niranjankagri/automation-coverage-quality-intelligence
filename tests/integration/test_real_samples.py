"""Import the real result files in samples/results and check them against independent facts.

Each producer writes its own totals into the file (``tests``, ``failures``, ``errors``,
``skipped`` on the suites). Those totals are computed by the framework, not by this project,
so comparing them with what the importer found shows that no result was lost or miscounted.
"""

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qualityintel.ingest.batch import import_results
from qualityintel.ingest.junit import read_junit_file
from qualityintel.models.enums import Outcome

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).parents[2] / "samples" / "results"
ALL_FILES = sorted(SAMPLES.rglob("*.xml"))
PRODUCERS = {
    "pytest-notes-api": "pytest",
    "pytest-notes-ui-chromium": "pytest",
    "robot-saucedemo-chrome": "robot-framework",
    "testng-enterprise-regression-firefox": "testng",
    "playwright-toolshop-firefox": "playwright",
}


def declared_totals(path: Path) -> dict[str, int]:
    """Totals the producer wrote: root attributes, or the sum of top-level suites."""
    root = ET.parse(path).getroot()
    holders = [root] if root.get("tests") is not None else [s for s in root if s.tag == "testsuite"]
    return {
        key: sum(int(h.get(key, "0")) for h in holders) for key in ("tests", "failures", "errors", "skipped")
    }


def test_every_sample_folder_is_known() -> None:
    """A new sample folder must be added to PRODUCERS (and to docs/ingestion.md)."""
    assert {p.name for p in SAMPLES.iterdir() if p.is_dir()} == set(PRODUCERS)
    assert len(ALL_FILES) >= 40


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_counts_match_the_producers_own_totals(path: Path) -> None:
    """The counts of tests, failures, errors and skips equal the totals the framework wrote."""
    run = read_junit_file(path).run
    counts = run.outcome_counts()
    totals = declared_totals(path)

    assert len(run.results) == totals["tests"]
    assert counts[Outcome.FAILED] == totals["failures"]
    assert counts[Outcome.ERROR] == totals["errors"]
    assert counts[Outcome.SKIPPED] == totals["skipped"]


@pytest.mark.parametrize("path", ALL_FILES, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_context_and_time_survive_the_import(path: Path) -> None:
    """Framework, browser, build and the run's start time are available for history."""
    run = read_junit_file(path).run
    date = path.name[:10]

    assert run.context.framework == PRODUCERS[path.parent.name]
    assert run.context.environment == "ci"
    assert run.context.build == path.name.split("_")[1]
    assert run.started_at is not None
    assert run.started_at.date().isoformat() == date
    assert all(r.duration_seconds is not None for r in run.results)


def test_all_samples_import_as_one_batch_without_errors() -> None:
    """The whole sample set imports cleanly: no errors, no duplicates, no warnings."""
    batch = import_results([SAMPLES])

    assert batch.complete
    assert len(batch.runs) == len(ALL_FILES)
    assert batch.duplicates == []
    assert batch.warnings == []
    assert {r.context.framework for r in batch.runs} == {"pytest", "robot-framework", "testng", "playwright"}


def test_real_selenium_timeout_is_kept_with_its_details() -> None:
    """The 13 Oct nightly failed once on Firefox; message and exception type are preserved."""
    run = read_junit_file(
        SAMPLES / "testng-enterprise-regression-firefox" / "2026-10-13_f5a40d5_38374469545.xml"
    ).run

    (failed,) = [r for r in run.results if r.outcome is Outcome.FAILED]
    assert failed.key == "com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer"
    assert failed.failure is not None
    assert failed.failure.type == "org.openqa.selenium.TimeoutException"
    assert failed.failure.message.startswith("Expected condition failed: data-ready='true'")


def test_playwright_attempts_show_failure_error_then_pass() -> None:
    """Run 39229363499 needed three attempts: 1 failure, then 2 errors, then all green."""
    folder = SAMPLES / "playwright-toolshop-firefox"
    attempts = [
        read_junit_file(folder / f"2026-10-19_07f8c24_39229363499-attempt{n}.xml").run for n in (1, 2, 3)
    ]

    summary = [(a.outcome_counts()[Outcome.FAILED], a.outcome_counts()[Outcome.ERROR]) for a in attempts]
    assert summary == [(1, 0), (0, 2), (0, 0)]
    assert [a.started_at for a in attempts] == sorted(a.started_at for a in attempts if a.started_at)
    assert attempts[0].started_at == datetime(2026, 10, 19, 9, 20, 47, tzinfo=UTC)


def test_robot_nested_suites_give_suite_and_classname() -> None:
    """Robot's nested suites end up as the innermost suite name and a dotted classname."""
    run = read_junit_file(next((SAMPLES / "robot-saucedemo-chrome").glob("*.xml"))).run
    login = next(r for r in run.results if r.name == "Valid Login Returns Tokens And User")

    assert login.suite == "01 Auth"
    assert login.classname == "Robot Framework Automation.Api.01 Auth"
