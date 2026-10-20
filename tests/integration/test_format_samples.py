"""Phase 5 acceptance: genuine Cypress (mochawesome) and Allure results import correctly and agree with JUnit.

Samples (samples/formats, see samples/README.md): Cypress API and UI runs of my TaskBoard
project, and five runs of the enterprise API suite, each kept as Allure results AND as the
Surefire JUnit XML that the same CI job wrote at the same time.
"""

import json
import statistics
from pathlib import Path

import pytest

from qualityintel.ingest.allure import read_allure_folder
from qualityintel.ingest.batch import import_results
from qualityintel.ingest.junit import read_junit_file
from qualityintel.ingest.mochawesome import read_mochawesome_file
from qualityintel.models.enums import Outcome

pytestmark = pytest.mark.integration

FORMATS = Path(__file__).parents[2] / "samples" / "formats"
CYPRESS = sorted(FORMATS.glob("cypress-*/*.json"))
ALLURE = sorted(p for p in (FORMATS / "allure-enterprise-api").iterdir() if p.is_dir())


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


def test_all_formats_import_together_from_one_folder() -> None:
    """A directory with mochawesome JSON, Allure folders and JUnit XML is one clean batch."""
    batch = import_results([FORMATS])

    assert batch.complete
    assert batch.warnings == []
    kinds = {r.context.framework for r in batch.runs}
    assert kinds == {"cypress", "testng"}
    assert len(batch.runs) == len(CYPRESS) + len(ALLURE) * 2  # Allure and JUnit copies of each run
