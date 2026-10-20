"""Phase 4 acceptance: trend values match the stored execution records.

The history database is built from the real samples with the documented command; the expected
values are then computed with plain SQL straight from its tables (no qualityintel code), and the
API's trend data must equal them.
"""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qualityintel.cli import EXIT_OK, main
from qualityintel.dashboard.app import create_app
from qualityintel.history.store import HistoryStore
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.workspace import Workspace

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).parents[2] / "samples"

# Latest run per context up to the end of each day, then its outcome counts (pure SQL)
DAILY_SQL = """
WITH days AS (SELECT DISTINCT substr(started_at, 1, 10) AS day FROM runs WHERE started_at IS NOT NULL),
latest AS (
  SELECT d.day, r.run_id
  FROM days d JOIN runs r ON substr(r.started_at, 1, 10) <= d.day
  WHERE r.started_at = (
    SELECT max(r2.started_at) FROM runs r2
    WHERE substr(r2.started_at, 1, 10) <= d.day
      AND r2.framework IS r.framework AND r2.environment IS r.environment
      AND r2.browser IS r.browser AND r2.platform IS r.platform)
)
SELECT l.day, res.outcome, count(*)
FROM latest l JOIN results res ON res.run_id = l.run_id
GROUP BY l.day, res.outcome ORDER BY l.day
"""


@pytest.fixture(scope="module")
def database(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """History of all sample runs, imported with a coverage snapshot of the sample catalog."""
    path = tmp_path_factory.mktemp("history") / "quality.db"
    code = main(
        [
            "history",
            "import",
            str(SAMPLES / "results"),
            "--database",
            str(path),
            "--catalog",
            str(SAMPLES / "catalog.toml"),
        ]
    )
    assert code == EXIT_OK
    return path


@pytest.fixture(scope="module")
def client(database: Path) -> TestClient:
    """The dashboard over that database, exactly as `qi dashboard --database` builds it."""
    with HistoryStore(database) as store:
        workspace = Workspace(load_catalog(SAMPLES / "catalog.toml"), store.runs(), store.snapshots())
    return TestClient(create_app(workspace))


def test_daily_counts_equal_a_plain_sql_recomputation(database: Path, client: TestClient) -> None:
    """Every day, every outcome: API value == SQL value from the runs and results tables."""
    with closing(sqlite3.connect(database)) as db:
        expected: dict[str, dict[str, int]] = {}
        for day, outcome, count in db.execute(DAILY_SQL):
            expected.setdefault(day, {"passed": 0, "failed": 0, "error": 0, "skipped": 0})[outcome] = count

    daily = client.get("/api/trends").json()["daily"]

    assert {p["day"]: p["counts"] for p in daily} == expected
    assert len(daily) == 13  # 7 to 19 Oct 2026


def test_per_run_series_equal_the_stored_runs(database: Path, client: TestClient) -> None:
    """Each run's counts and summed duration equal its rows in the results table."""
    with closing(sqlite3.connect(database)) as db:
        stored = {
            run_id: (passed, failed, round(duration, 3))
            for run_id, passed, failed, duration in db.execute(
                "SELECT run_id, sum(outcome = 'passed'), sum(outcome IN ('failed', 'error')), total(duration_seconds) "
                "FROM results GROUP BY run_id"
            )
        }

    series = client.get("/api/trends").json()["runs"]

    seen = {}
    for runs in series.values():
        for run in runs:
            seen[run["run_id"]] = (
                run["counts"]["passed"],
                run["counts"]["failed"] + run["counts"]["error"],
                run["duration_seconds"],
            )
    assert seen == stored


def test_the_real_failures_appear_on_their_days(client: TestClient) -> None:
    """13 Oct: the Selenium timeout (1 failed). 19 Oct: Playwright attempt 3 replaced attempts 1-2."""
    daily = {p["day"]: p for p in client.get("/api/trends").json()["daily"]}

    assert daily["2026-10-13"]["counts"]["failed"] == 1
    assert daily["2026-10-14"]["counts"]["failed"] == 0
    assert daily["2026-10-19"]["counts"]["failed"] + daily["2026-10-19"]["counts"]["error"] == 0
    assert all(p["carried"] == [] for p in daily.values())  # every suite ran on every day it existed


def test_growing_set_of_suites_is_flagged_not_hidden(client: TestClient) -> None:
    """Robot starts on 9 Oct, pytest on 13 Oct, Playwright on 17 Oct: totals jump, a note says why."""
    body = client.get("/api/trends").json()
    added = {p["day"]: p["added"] for p in body["daily"] if p["added"]}

    assert added == {
        "2026-10-09": ["robot-framework/ci/chrome/linux"],
        "2026-10-13": ["pytest/ci/-/linux", "pytest/ci/chromium/linux"],
        "2026-10-17": ["playwright/ci/firefox/linux"],
    }
    assert any(
        "the set of run contexts grows on 2026-10-09, 2026-10-13, 2026-10-17" in n for n in body["notes"]
    )


def test_coverage_snapshot_is_recorded_once_and_reported_honestly(database: Path, client: TestClient) -> None:
    """One catalog version so far: one snapshot with the sample numbers and a note, not a trend line."""
    assert (
        main(
            [
                "history",
                "import",
                str(SAMPLES / "results"),
                "--database",
                str(database),
                "--catalog",
                str(SAMPLES / "catalog.toml"),
            ]
        )
        == EXIT_OK
    )

    body = client.get("/api/trends").json()
    with HistoryStore(database) as store:
        assert len(store.snapshots()) == 1  # the second import found the catalog unchanged
    (snapshot,) = body["coverage"]
    assert (snapshot["requirement_coverage"]["text"], snapshot["automation_coverage"]["text"]) == (
        "90.5 % (38/42)",
        "86.0 % (37/43)",
    )
    assert any("one coverage snapshot so far" in note for note in body["notes"])


def test_filters_select_runs_by_build_and_date(client: TestClient) -> None:
    """since/until bound the days; build keeps only that build's runs."""
    window = client.get("/api/trends", params={"since": "2026-10-13", "until": "2026-10-15"}).json()
    build = client.get("/api/trends", params={"build": "f5a40d5"}).json()

    assert [p["day"] for p in window["daily"]] == ["2026-10-13", "2026-10-14", "2026-10-15"]
    assert list(build["runs"]) == ["testng / ci / firefox / linux"]
    assert client.get("/api/trends", params={"since": "2026-10-15", "until": "2026-10-13"}).status_code == 422
    assert client.get("/api/trends", params={"since": "13.10.2026"}).status_code == 422


def test_empty_scope_has_no_points_and_says_so(client: TestClient) -> None:
    """A date range without runs: no invented points, a note instead."""
    body = client.get("/api/trends", params={"since": "2030-01-01"}).json()

    assert body["daily"] == []
    assert body["runs"] == {}
    assert "no runs in this scope" in body["notes"]
