import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from qualityintel.history.store import SCHEMA_VERSION, HistoryError, HistoryStore
from qualityintel.ingest.batch import import_results
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob

from ..traceability.helpers import result, run

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[3] / "samples" / "results"


def test_runs_survive_a_round_trip_unchanged(tmp_path: Path) -> None:
    """Every field of every real sample run comes back exactly as it was stored."""
    original = import_results([SAMPLES]).runs
    database = tmp_path / "history.db"

    with HistoryStore(database) as store:
        assert store.add_all(original) == (len(original), 0)
    with HistoryStore(database) as store:
        loaded = store.runs()

    assert {r.run_id: r for r in loaded} == {r.run_id: r for r in original}


def test_same_run_is_stored_once(tmp_path: Path) -> None:
    """Importing a file again (same content hash) adds nothing."""
    first = run(result("a"), result("b", Outcome.FAILED, failure={"message": "x"}), day=1)

    with HistoryStore(tmp_path / "h.db") as store:
        assert store.add(first) is True
        assert store.add(first) is False
        assert store.add_all([first, run(result("a"), day=2)]) == (1, 1)
        assert store.count() == (2, 3)


def test_runs_come_back_oldest_first_with_undated_first(tmp_path: Path) -> None:
    """Order is by real start time, whatever the insert order."""
    late, early, undated = (
        run(result("a"), day=9),
        run(result("a"), day=2),
        run(result("a"), day=None, source="u.xml"),
    )

    with HistoryStore(tmp_path / "h.db") as store:
        store.add_all([late, undated, early])
        assert [r.started_at.day if r.started_at else None for r in store.runs()] == [None, 2, 9]


def test_failure_details_round_trip_including_empty_ones(tmp_path: Path) -> None:
    """<skipped/> without a message keeps empty details; no failure stays None."""
    skipped = result("s", Outcome.SKIPPED, failure={})
    passed = result("p")

    with HistoryStore(tmp_path / "h.db") as store:
        store.add(run(skipped, passed, day=1))
        loaded = {r.name: r for r in store.runs()[0].results}

    assert loaded["s"].failure is not None
    assert loaded["s"].failure.message == ""
    assert loaded["p"].failure is None


def test_remove_deletes_the_run_and_its_results(tmp_path: Path) -> None:
    """Foreign keys cascade: no orphan results stay behind."""
    stored = run(result("a"), result("b"), day=1)

    with HistoryStore(tmp_path / "h.db") as store:
        store.add(stored)
        assert store.remove(stored.run_id) is True
        assert store.remove(stored.run_id) is False
        assert store.count() == (0, 0)


def test_failed_write_leaves_nothing_behind(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A run and its results are one transaction: an error in the middle rolls back the run row."""
    store = HistoryStore(tmp_path / "h.db")
    good = run(result("a"), day=1)

    def broken_executemany(*args: object) -> None:
        raise sqlite3.OperationalError("disk full")

    original_connection = store._db

    class Wrapper:
        """Delegates to the real connection but fails on executemany."""

        def __getattr__(self, name: str) -> object:
            return getattr(original_connection, name)

        def executemany(self, *args: object) -> None:
            broken_executemany(*args)

    monkeypatch.setattr(store, "_db", Wrapper())
    with pytest.raises(sqlite3.OperationalError):
        store.add(good)
    monkeypatch.setattr(store, "_db", original_connection)

    assert store.count() == (0, 0)
    store.close()


def test_newer_schema_is_refused(tmp_path: Path) -> None:
    """A database from a newer version is not read with old assumptions."""
    path = tmp_path / "h.db"
    HistoryStore(path).close()
    # closing(): a sqlite3 connection used as a context manager only commits, it does not close
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION + 1,))

    with pytest.raises(HistoryError, match="written by a newer version"):
        HistoryStore(path)


def test_a_file_that_is_not_a_database_is_refused(tmp_path: Path) -> None:
    """Pointing QI_DATABASE at a result file gives a clear error."""
    path = tmp_path / "junit.xml"
    path.write_text("<testsuite/>" * 200, encoding="utf-8")

    with pytest.raises(HistoryError, match="cannot be used as a history database"):
        HistoryStore(path)


def test_parent_folder_is_created(tmp_path: Path) -> None:
    """The default .qi/quality.db works in a clean checkout."""
    with HistoryStore(tmp_path / ".qi" / "quality.db") as store:
        assert store.count() == (0, 0)


def test_pipeline_job_round_trips_and_runs_of_a_job_attempt_are_found(tmp_path: Path) -> None:
    """Pipeline id, job, attempt, branch and commit come back; plain runs stay without one."""
    job = PipelineJob(pipeline_id="39238241112", job="api", attempt=2, branch="main", commit="80e331e")
    in_pipeline = run(result("A"), day=1).model_copy(update={"pipeline": job})
    plain = run(result("B"), day=2)

    with HistoryStore(tmp_path / "h.db") as store:
        store.add_all([in_pipeline, plain])
        loaded = {r.run_id: r for r in store.runs()}
        found = store.job_runs("39238241112", "api", 2)
        other_attempt = store.job_runs("39238241112", "api", 1)

    assert loaded[in_pipeline.run_id].pipeline == job
    assert loaded[plain.run_id].pipeline is None
    assert found == {in_pipeline.run_id}
    assert other_attempt == set()


def test_version_2_database_gains_the_pipeline_columns(tmp_path: Path) -> None:
    """A schema 2 file (runs table without pipeline columns) opens and keeps its runs."""
    path = tmp_path / "v2.db"
    with closing(sqlite3.connect(path)) as db, db:
        db.executescript(SCHEMA_2_RUNS)
        db.execute(
            "INSERT INTO runs VALUES ('" + "a" * 64 + "', 'junit.xml', 'pytest', NULL, NULL, NULL, '1.0', "
            "'2026-10-19T09:00:00+00:00', '2026-10-19T10:00:00+00:00')"
        )

    with HistoryStore(path) as store:
        (old,) = store.runs()
        store.add(run(result("A")).model_copy(update={"pipeline": PipelineJob(pipeline_id="1", job="api")}))
        assert store.count() == (2, 1)

    assert old.pipeline is None
    assert old.context.build == "1.0"
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION == 6


# The runs table and version row as schema 2 wrote them (before pipeline columns existed)
SCHEMA_2_RUNS = """
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO schema_version VALUES (2);
CREATE TABLE runs (
    run_id TEXT PRIMARY KEY, source TEXT NOT NULL, framework TEXT, environment TEXT, browser TEXT,
    platform TEXT, build TEXT, started_at TEXT, imported_at TEXT NOT NULL
);
"""


def test_repository_is_stored_and_a_version_4_database_gains_the_column(tmp_path: Path) -> None:
    """The pipeline's repository round-trips; an older file keeps its runs and gets the column."""
    path = tmp_path / "v4.db"
    with HistoryStore(path) as store:
        store.add(run(result("A"), day=1))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("ALTER TABLE runs DROP COLUMN repository")
        db.execute("UPDATE schema_version SET version = 4")

    job = PipelineJob(pipeline_id="r#1", job="api", repository="niranjankagri/python-pytest-framework")
    with HistoryStore(path) as store:
        store.add(run(result("B"), day=2).model_copy(update={"pipeline": job}))
        stored = {r.pipeline.repository if r.pipeline else None for r in store.runs()}

    assert stored == {None, "niranjankagri/python-pytest-framework"}


def test_runs_collected_before_schema_5_get_the_repository_of_their_collection(tmp_path: Path) -> None:
    """The upgrade copies the repository from the collection record; other runs stay without one."""
    from datetime import UTC, datetime

    from qualityintel.models.collection import PipelineCollection

    path = tmp_path / "old.db"
    collected = run(result("A"), day=1).model_copy(
        update={"pipeline": PipelineJob(pipeline_id="r#1", job="api")}
    )
    record = PipelineCollection(
        pipeline_id="r#1",
        attempt=1,
        repository="niranjankagri/robot-framework-automation",
        workflow="ci.yml",
        conclusion="success",
        collected_at=datetime(2026, 10, 20, tzinfo=UTC),
        state="complete",
    )
    with HistoryStore(path) as store:
        store.add_collection(record, [collected])
        store.add(run(result("B"), day=2))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("UPDATE runs SET repository = NULL")
        db.execute("UPDATE schema_version SET version = 4")

    with HistoryStore(path) as store:
        repositories = sorted(str(r.pipeline.repository if r.pipeline else None) for r in store.runs())

    assert repositories == ["None", "niranjankagri/robot-framework-automation"]


def test_prune_deletes_old_runs_results_and_records_but_keeps_the_latest_snapshot(tmp_path: Path) -> None:
    """Everything before the cutoff goes, with its results; the latest snapshot of each catalog stays."""
    from datetime import UTC, datetime, timedelta

    from qualityintel.history.trends import CoverageSnapshot
    from qualityintel.models.metrics import Ratio

    runs = import_results([Path(__file__).parents[3] / "samples" / "results"]).runs
    with HistoryStore(tmp_path / "h.db") as store:
        store.add_all(runs)
        starts = sorted(r.started_at for r in runs if r.started_at is not None)
        middle = starts[len(starts) // 2]
        expected_runs = sum(1 for r in runs if (r.started_at or datetime.now(UTC)) < middle)
        expected_results = sum(len(r.results) for r in runs if (r.started_at or datetime.now(UTC)) < middle)

        for days, sha in ((30, "a"), (20, "b")):
            store.add_snapshot(
                CoverageSnapshot(
                    taken_at=middle - timedelta(days=days),
                    catalog="catalog.toml",
                    catalog_sha256=sha,
                    requirements=1,
                    requirement_coverage=Ratio(numerator=1, denominator=1),
                    automation_coverage=Ratio(numerator=1, denominator=1),
                    automated_requirement_coverage=Ratio(numerator=1, denominator=1),
                )
            )

        pruned = store.prune(middle)

        assert (pruned.runs, pruned.results) == (expected_runs, expected_results)
        assert store.count() == (
            len(runs) - expected_runs,
            sum(len(r.results) for r in runs) - expected_results,
        )
        assert all(r.started_at is None or r.started_at >= middle for r in store.runs())
        assert store.check() == []
        assert pruned.snapshots == 1
        assert [snapshot.catalog_sha256 for snapshot in store.snapshots()] == ["b"]


def test_opening_a_schema_5_file_dates_collected_runs_from_their_pipeline(tmp_path: Path) -> None:
    """Runs collected before schema 6 without a start time get their CI run's start."""
    path = tmp_path / "old.db"
    with HistoryStore(path):
        pass
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO runs (run_id, source, imported_at, pipeline_id, job, attempt) "
            "VALUES ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 'it/TEST-A.xml', '2026-10-20T21:00:00+00:00', 'it#1', 'it', 1)"
        )
        db.execute(
            "INSERT INTO collections VALUES ('it#1', 1, 'o/it', 'ci.yml', 1, 'push', 'main', 'abc', "
            "'success', 'https://x', '2026-10-20T20:06:18+00:00', '2026-10-20T21:00:00+00:00', "
            "'complete', 1, 0, '[]')"
        )
        db.execute("UPDATE schema_version SET version = 5")

    with HistoryStore(path) as store:
        (stored,) = store.runs()

    assert stored.started_at is not None
    assert stored.started_at.isoformat() == "2026-10-20T20:06:18+00:00"
