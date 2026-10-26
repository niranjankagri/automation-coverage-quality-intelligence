"""Phase 5 acceptance: genuine Cypress (mochawesome) and Allure results import correctly and agree with JUnit.

Samples (samples/formats, see samples/README.md): Cypress API and UI runs of my TaskBoard
project, five runs of the enterprise API suite, each kept as Allure results AND as the
Surefire JUnit XML that the same CI job wrote at the same time, and one Playwright CI run
(four projects) kept as Playwright's JSON report AND as its JUnit XML of the same jobs.
"""

import json
import statistics
from pathlib import Path

import pytest

from qualityintel.ingest.allure import read_allure_folder
from qualityintel.ingest.batch import import_results
from qualityintel.ingest.junit import read_junit_file
from qualityintel.ingest.mochawesome import read_mochawesome_file
from qualityintel.ingest.playwright_json import read_playwright_file
from qualityintel.models.enums import Outcome

pytestmark = pytest.mark.integration

FORMATS = Path(__file__).parents[2] / "samples" / "formats"
CYPRESS = sorted(FORMATS.glob("cypress-*/*.json"))
ALLURE = sorted(p for p in (FORMATS / "allure-enterprise-api").iterdir() if p.is_dir())
PLAYWRIGHT = sorted((FORMATS / "playwright-toolshop").glob("*.json"))


@pytest.mark.parametrize("path", CYPRESS, ids=lambda p: f"{p.parent.name}/{p.name}")
def test_cypress_counts_match_the_reports_own_stats(path: Path) -> None:
    """Tests, passes, failures and pending equal the totals mochawesome wrote into the report."""
    stats = json.loads(path.read_text(encoding="utf-8"))["stats"]
    run = read_mochawesome_file(path).run
    counts = run.outcome_counts()

    assert len(run.results) == stats["tests"]
    assert counts[Outcome.PASSED] == stats["passes"]
    assert counts[Outcome.FAILED] == stats["failures"]
    assert counts[Outcome.SKIPPED] == stats["pending"] + stats.get("skipped", 0)
    assert run.context.framework == "cypress"
    assert run.context.build == path.name.split("_")[1]
    assert run.started_at is not None
    assert run.started_at.date().isoformat() == path.name[:10]


@pytest.mark.parametrize("folder", ALLURE, ids=lambda p: p.name)
def test_allure_counts_match_the_result_files(folder: Path) -> None:
    """One result per *-result.json (no retries in these runs); statuses counted by hand."""
    files = list(folder.glob("*-result.json"))
    statuses = [json.loads(f.read_text(encoding="utf-8"))["status"] for f in files]
    run = read_allure_folder(folder).run

    assert len(run.results) == len(files)
    assert run.outcome_counts()[Outcome.PASSED] == statuses.count("passed")
    assert run.context.framework == "testng"
    assert run.context.build is not None
    assert run.context.build.startswith(folder.name.split("_")[1])  # the commit of the CI run


@pytest.mark.parametrize("folder", ALLURE, ids=lambda p: p.name)
def test_allure_and_junit_of_the_same_run_agree(folder: Path) -> None:
    """Same CI job, two formats: same tests, same outcomes, close durations.

    Plain test methods have identical keys in both formats. Data-driven rows are named
    differently (TestNG's JUnit names list the values in argument order with a row number,
    Allure in its own parameter order), so they are matched by method and by parameter values.
    """
    allure = {r.key: r for r in read_allure_folder(folder).run.results}
    junit = {
        r.key: r
        for r in read_junit_file(
            FORMATS / "junit-enterprise-api" / folder.name / "TEST-TestSuite.xml"
        ).run.results
    }

    assert len(allure) == len(junit)
    plain = set(allure) & set(junit)
    assert len(plain) >= 40
    assert all(allure[k].outcome is junit[k].outcome for k in plain)

    rows_allure = sorted(set(allure) - plain)
    rows_junit = sorted(set(junit) - plain)
    for key in rows_allure:
        method, values = key.split("[", 1)
        parts = [v for v in values[:-1].split(", ") if v]
        matches = [j for j in rows_junit if j.startswith(method + "[") and all(part in j for part in parts)]
        assert matches, f"no JUnit row for {key}"
        assert junit[matches[0]].outcome is allure[key].outcome
    assert len(rows_allure) == len(rows_junit)

    differences = [abs((allure[k].duration_seconds or 0) - (junit[k].duration_seconds or 0)) for k in plain]
    assert statistics.median(differences) < 0.25  # measured: about 0.08 s
    assert max(differences) < 3.0  # measured: up to 2.2 s (the two reporters time a test differently)


@pytest.mark.parametrize("path", PLAYWRIGHT, ids=lambda p: p.stem.rsplit("_", 1)[1])
def test_playwright_json_and_junit_of_the_same_job_agree(path: Path) -> None:
    """Same CI job, two reporters: same keys, same outcomes, the counts of Playwright's own stats.

    The keys are equal, so a producer can move from JUnit to JSON without losing test history.
    """
    stats = json.loads(path.read_text(encoding="utf-8"))["stats"]
    from_json = {r.key: r for r in read_playwright_file(path).run.results}
    from_junit = {
        r.key: r
        for r in read_junit_file(FORMATS / "junit-playwright-toolshop" / f"{path.stem}.xml").run.results
    }

    assert set(from_json) == set(from_junit)
    assert all(from_json[k].outcome is from_junit[k].outcome for k in from_json)
    assert len(from_json) == stats["expected"] + stats["unexpected"] + stats["flaky"] + stats["skipped"]
    assert sum(r.passed_after_retry for r in from_json.values()) == stats["flaky"]


def test_the_flaky_checkout_test_is_visible_only_in_the_json_report() -> None:
    """CI run 40280345033, chromium: the checkout test failed once and passed on its retry.

    Playwright's JUnit says passed (no retries); the JSON report gives the retry, so the test
    becomes a flaky candidate.
    """
    name = "2026-10-26_6da9aba_40280345033_chromium"
    arrow = " \N{SINGLE RIGHT-POINTING ANGLE QUOTATION MARK} "
    key = f"ui/checkout.spec.ts::Checkout as a logged-in customer{arrow}customer can order two products"
    from_json = {
        r.key: r for r in read_playwright_file(FORMATS / "playwright-toolshop" / f"{name}.json").run.results
    }
    from_junit = {
        r.key: r for r in read_junit_file(FORMATS / "junit-playwright-toolshop" / f"{name}.xml").run.results
    }

    assert from_junit[key].outcome is Outcome.PASSED
    assert from_junit[key].retries == 0
    assert from_json[key].outcome is Outcome.PASSED
    assert from_json[key].retries == 1
    assert [k for k, r in from_json.items() if r.retries] == [key]


def test_all_formats_import_together_from_one_folder() -> None:
    """A directory with mochawesome JSON, Allure folders and JUnit XML is one clean batch."""
    batch = import_results([FORMATS])

    assert batch.complete
    kinds = {r.context.framework for r in batch.runs}
    assert kinds == {"cypress", "testng", "playwright"}
    # Allure and JUnit copies of each API run, plus the nightly full run; JSON and JUnit copies
    # of each Playwright job
    assert len(batch.runs) == len(CYPRESS) + len(ALLURE) * 2 + 1 + len(PLAYWRIGHT) * 2
    # The only warning: the nightly's repeated invocations share a key (as in JUnit XML)
    assert all("everyThreadGetsItsOwnBrowser" in w for w in batch.warnings)


def test_repeated_invocations_in_the_real_nightly_count_every_time() -> None:
    """The 20 Oct nightly's Full suite: its CI log says 169 passed; 169 results, no invented retries.

    Before the fix the four invocations of everyThreadGetsItsOwnBrowser (TestNG invocationCount)
    were read as one test with three retries, so 166 results were imported.
    """
    (folder,) = sorted((FORMATS / "allure-enterprise-nightly-full").iterdir())
    run = read_allure_folder(folder).run

    assert len(run.results) == 169
    assert run.outcome_counts()[Outcome.PASSED] == 169
    assert sum(r.retries for r in run.results) == 0
    assert sum(r.name == "everyThreadGetsItsOwnBrowser" for r in run.results) == 4
