"""SQLite store for imported runs ([ADR 0003](../../../docs/adr/0003-sqlite-first.md)).

All SQL of the project lives in this module. The analysis code works on plain
:class:`TestRun` objects, so another database could replace this module alone.

Design points:

- the run id (SHA-256 of the result file) is the primary key, so importing the same file twice
  stores it once: :meth:`HistoryStore.add` returns ``False`` for a run that is already there;
- a run and its results are written in one transaction: a crash never leaves half a run;
- the schema has a version number; opening a database written by a newer version fails
  instead of guessing;
- one writer at a time (SQLite's own locking); concurrent CI jobs should write separate files;
- one attempt of a pipeline job is imported once: :meth:`HistoryStore.job_runs` lets the caller
  refuse a second, different import of the same job attempt (docs/pipelines.md).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import TracebackType

from qualityintel.history.trends import CoverageSnapshot
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio
from qualityintel.models.results import FailureDetails, PipelineJob, RunContext, TestResult, TestRun

# 1: runs and results. 2: coverage snapshots. 3: pipeline columns on runs.
# Older files are upgraded when opened.
SCHEMA_VERSION = 3
PIPELINE_COLUMNS = {
    "pipeline_id": "TEXT",
    "job": "TEXT",
    "attempt": "INTEGER",
    "branch": "TEXT",
    "git_commit": "TEXT",
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    framework    TEXT,
    environment  TEXT,
    browser      TEXT,
    platform     TEXT,
    build        TEXT,
    started_at   TEXT,
    imported_at  TEXT NOT NULL,
    pipeline_id  TEXT,
    job          TEXT,
    attempt      INTEGER,
    branch       TEXT,
    git_commit   TEXT
);
CREATE TABLE IF NOT EXISTS results (
    run_id           TEXT    NOT NULL REFERENCES runs (run_id) ON DELETE CASCADE,
    position         INTEGER NOT NULL,
    name             TEXT    NOT NULL,
    classname        TEXT    NOT NULL,
    suite            TEXT    NOT NULL,
    outcome          TEXT    NOT NULL CHECK (outcome IN ('passed', 'failed', 'error', 'skipped')),
    duration_seconds REAL    CHECK (duration_seconds IS NULL OR duration_seconds >= 0),
    timestamp        TEXT,
    failure_message  TEXT,
    failure_type     TEXT,
    failure_text     TEXT,
    test_ids         TEXT    NOT NULL,
    retries          INTEGER NOT NULL CHECK (retries >= 0),
    PRIMARY KEY (run_id, position)
);
CREATE INDEX IF NOT EXISTS results_by_test ON results (classname, name);
CREATE INDEX IF NOT EXISTS runs_by_start ON runs (started_at);
CREATE TABLE IF NOT EXISTS coverage_snapshots (
    taken_at                    TEXT    NOT NULL,
    catalog                     TEXT    NOT NULL,
    catalog_sha256              TEXT    NOT NULL,
    requirements                INTEGER NOT NULL,
    requirement_coverage        TEXT    NOT NULL,
    automation_coverage         TEXT    NOT NULL,
    automated_requirement_coverage TEXT NOT NULL
);
"""


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class HistoryError(RuntimeError):
    """The history database cannot be used (unreadable, or written by a newer version)."""


class HistoryStore:
    """Execution history in one SQLite file. Use as a context manager."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.name != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(self.path))
        try:
            self._db.execute("PRAGMA foreign_keys = ON")
            self._migrate()
        except sqlite3.DatabaseError as error:
            self._db.close()
            raise HistoryError(f"{self.path.name}: cannot be used as a history database ({error})") from None
        except HistoryError:
            # A refused database must not keep its file handle open
            self._db.close()
            raise

    def __enter__(self) -> HistoryStore:
        return self

    def __exit__(
        self, kind: type[BaseException] | None, error: BaseException | None, trace: TracebackType | None
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the connection."""
        self._db.close()

    def add(self, run: TestRun) -> bool:
        """Store a run with its results; ``False`` when this exact run is already stored."""
        with self._transaction() as db:
            exists = db.execute("SELECT 1 FROM runs WHERE run_id = ?", (run.run_id,)).fetchone()
            if exists:
                return False
            context = run.context
            pipeline = run.pipeline
            db.execute(
                "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    run.run_id,
                    run.source,
                    context.framework,
                    context.environment,
                    context.browser,
                    context.platform,
                    context.build,
                    _iso(run.started_at),
                    datetime.now(UTC).isoformat(),
                    *(
                        (
                            pipeline.pipeline_id,
                            pipeline.job,
                            pipeline.attempt,
                            pipeline.branch,
                            pipeline.commit,
                        )
                        if pipeline
                        else (None,) * len(PIPELINE_COLUMNS)
                    ),
                ),
            )
            db.executemany(
                "INSERT INTO results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        run.run_id,
                        position,
                        r.name,
                        r.classname,
                        r.suite,
                        r.outcome.value,
                        r.duration_seconds,
                        _iso(r.timestamp),
                        r.failure.message if r.failure else None,
                        r.failure.type if r.failure else None,
                        r.failure.text if r.failure else None,
                        json.dumps(list(r.test_ids)),
                        r.retries,
                    )
                    for position, r in enumerate(run.results)
                ],
            )
        return True

    def add_all(self, runs: Iterable[TestRun]) -> tuple[int, int]:
        """Store several runs; returns ``(added, already stored)``."""
        added = skipped = 0
        for run in runs:
            if self.add(run):
                added += 1
            else:
                skipped += 1
        return added, skipped

    def runs(self) -> list[TestRun]:
        """Every stored run with its results, oldest first (undated runs first)."""
        rows = self._db.execute(
            "SELECT run_id, source, framework, environment, browser, platform, build, started_at, "
            f"{', '.join(PIPELINE_COLUMNS)} FROM runs ORDER BY started_at IS NOT NULL, started_at, source"
        ).fetchall()
        results = self._results_by_run()
        runs = [
            TestRun(
                run_id=run_id,
                source=source,
                context=RunContext(
                    framework=framework,
                    environment=environment,
                    browser=browser,
                    platform=platform,
                    build=build,
                ),
                started_at=_parse(started_at),
                results=tuple(results.get(run_id, ())),
                pipeline=PipelineJob(
                    pipeline_id=pipeline_id, job=job, attempt=attempt, branch=branch, commit=commit
                )
                if pipeline_id is not None
                else None,
            )
            for (
                run_id,
                source,
                framework,
                environment,
                browser,
                platform,
                build,
                started_at,
                pipeline_id,
                job,
                attempt,
                branch,
                commit,
            ) in rows
        ]
        # Sorted again on real datetimes: ISO text with and without fractions does not sort reliably
        return sorted(runs, key=lambda r: (r.started_at is not None, r.started_at or _EPOCH, r.source))

    def job_runs(self, pipeline_id: str, job: str, attempt: int) -> set[str]:
        """Run ids already stored for one attempt of one pipeline job."""
        rows = self._db.execute(
            "SELECT run_id FROM runs WHERE pipeline_id = ? AND job = ? AND attempt = ?",
            (pipeline_id, job, attempt),
        )
        return {row[0] for row in rows}

    def count(self) -> tuple[int, int]:
        """``(runs, results)`` stored."""
        runs = self._db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        results = self._db.execute("SELECT COUNT(*) FROM results").fetchone()[0]
        return int(runs), int(results)

    def remove(self, run_id: str) -> bool:
        """Delete one run and its results; ``False`` when it was not stored."""
        with self._transaction() as db:
            deleted = db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,)).rowcount
        return deleted > 0

    def add_snapshot(self, snapshot: CoverageSnapshot) -> bool:
        """Store a coverage snapshot unless the catalog is unchanged since the latest one."""
        latest = self._db.execute(
            "SELECT catalog_sha256 FROM coverage_snapshots WHERE catalog = ? ORDER BY taken_at DESC LIMIT 1",
            (snapshot.catalog,),
        ).fetchone()
        if latest is not None and latest[0] == snapshot.catalog_sha256:
            return False
        with self._transaction() as db:
            db.execute(
                "INSERT INTO coverage_snapshots VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    _iso(snapshot.taken_at),
                    snapshot.catalog,
                    snapshot.catalog_sha256,
                    snapshot.requirements,
                    *(
                        f"{ratio.numerator}/{ratio.denominator}"
                        for ratio in (
                            snapshot.requirement_coverage,
                            snapshot.automation_coverage,
                            snapshot.automated_requirement_coverage,
                        )
                    ),
                ),
            )
        return True

    def snapshots(self) -> list[CoverageSnapshot]:
        """Every coverage snapshot, oldest first."""
        rows = self._db.execute("SELECT * FROM coverage_snapshots ORDER BY taken_at").fetchall()
        return [
            CoverageSnapshot(
                taken_at=_parse(taken_at) or datetime.now(UTC),
                catalog=catalog,
                catalog_sha256=sha,
                requirements=requirements,
                requirement_coverage=_ratio(req),
                automation_coverage=_ratio(auto),
                automated_requirement_coverage=_ratio(auto_req),
            )
            for taken_at, catalog, sha, requirements, req, auto, auto_req in rows
        ]

    # ---- internals -----------------------------------------------------------------------

    def _migrate(self) -> None:
        """Create the schema, or check that an existing database has a version we understand."""
        self._db.executescript(SCHEMA)
        row = self._db.execute("SELECT version FROM schema_version").fetchone()
        if row is None:
            self._db.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
            self._db.commit()
        elif row[0] > SCHEMA_VERSION:
            raise HistoryError(
                f"{self.path.name}: written by a newer version "
                f"(schema {row[0]}, this version reads {SCHEMA_VERSION})"
            )
        elif row[0] < SCHEMA_VERSION:
            # New tables were created above (IF NOT EXISTS); new columns are added here.
            # Existing rows keep their data; their pipeline columns are NULL (not part of one)
            columns = {info[1] for info in self._db.execute("PRAGMA table_info(runs)")}
            with self._transaction() as db:
                for name, kind in PIPELINE_COLUMNS.items():
                    if name not in columns:
                        db.execute(f"ALTER TABLE runs ADD COLUMN {name} {kind}")
                db.execute("UPDATE schema_version SET version = ?", (SCHEMA_VERSION,))
        self._db.execute("CREATE INDEX IF NOT EXISTS runs_by_pipeline ON runs (pipeline_id, job, attempt)")
        self._db.commit()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on any error."""
        try:
            yield self._db
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def _results_by_run(self) -> dict[str, list[TestResult]]:
        """All results grouped by run, in file order."""
        grouped: dict[str, list[TestResult]] = {}
        query = (
            "SELECT run_id, name, classname, suite, outcome, duration_seconds, timestamp, failure_message, "
            "failure_type, failure_text, test_ids, retries FROM results ORDER BY run_id, position"
        )
        for row in self._db.execute(query):
            (
                run_id,
                name,
                classname,
                suite,
                outcome,
                duration,
                timestamp,
                message,
                kind,
                text,
                ids,
                retries,
            ) = row
            has_failure = message is not None or kind is not None or text is not None
            grouped.setdefault(run_id, []).append(
                TestResult(
                    name=name,
                    classname=classname,
                    suite=suite,
                    outcome=Outcome(outcome),
                    duration_seconds=duration,
                    timestamp=_parse(timestamp),
                    failure=FailureDetails(message=message or "", type=kind or "", text=text or "")
                    if has_failure
                    else None,
                    test_ids=tuple(json.loads(ids)),
                    retries=retries,
                )
            )
        return grouped


def _ratio(text: str) -> Ratio:
    """``"38/42"`` back to a Ratio."""
    numerator, denominator = text.split("/")
    return Ratio(numerator=int(numerator), denominator=int(denominator))


def _iso(value: datetime | None) -> str | None:
    """Datetime as ISO text in UTC (sorts correctly as text)."""
    return None if value is None else value.astimezone(UTC).isoformat()


def _parse(value: str | None) -> datetime | None:
    """ISO text back to an aware datetime."""
    return None if value is None else datetime.fromisoformat(value)
