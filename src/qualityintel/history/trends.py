"""Trends over time: daily execution snapshots and recorded coverage snapshots.

**Daily snapshot.** For every day on which at least one run started, the snapshot is what a
release decision would have seen at the end of that day: the latest run of each run context
started on or before that day (docs/metrics.md, "Execution status"). A context without a run that
day contributes its older latest run; that context is listed as *carried over*, so a chart never
silently mixes today's results with last week's as if they were one run.

**Coverage snapshot.** Coverage depends on the catalog, which changes on its own schedule. The
history therefore stores the catalog's three coverage metrics each time ``qi history import
--catalog`` runs with a changed catalog; trends of coverage are drawn only from those records,
never reconstructed. The catalog applied to past runs in daily snapshots is the current one: a
requirement added today shows as "not run" on earlier days.

**Repository trends** (:func:`repository_trends`, M13). Per repository, the snapshot at the end
of the newest day with runs is set against the snapshot ``days`` earlier: results, failed tests,
pass rate, and the tests that started or stopped failing in between (docs/metrics.md).
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from qualityintel.models.catalog import Catalog
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import TestRun
from qualityintel.traceability.coverage import Filters, analyse_coverage
from qualityintel.traceability.report import build_report, context_key, latest_runs


@dataclass(frozen=True)
class DailyPoint:
    """The snapshot at the end of one day.

    Attributes:
        counts: Outcomes of every result in the day's snapshot.
        duration_seconds: Sum of the recorded test durations in the snapshot.
        requirement_status: Number of in-scope requirements per execution status.
        contexts: Run contexts in the snapshot.
        carried: Contexts (as ``framework/environment/browser/platform``) whose latest run
            started before this day.
        added: Contexts that appear for the first time on this day (not on the first day): from
            here on the totals include a suite that was not there before, so they are not
            comparable with earlier days.
    """

    day: date
    counts: dict[Outcome, int]
    pass_rate: Ratio
    duration_seconds: float
    requirement_status: dict[str, int]
    contexts: int
    carried: tuple[str, ...]
    added: tuple[str, ...] = ()


@dataclass(frozen=True)
class CoverageSnapshot:
    """The catalog's coverage metrics at one moment (stored in the history database)."""

    taken_at: datetime
    catalog: str
    catalog_sha256: str
    requirements: int
    requirement_coverage: Ratio
    automation_coverage: Ratio
    automated_requirement_coverage: Ratio


def daily_trend(
    runs: Iterable[TestRun], catalog: Catalog, filters: Filters | None = None
) -> list[DailyPoint]:
    """One snapshot per day with runs (UTC dates, oldest first); undated runs are left out."""
    dated = sorted((r for r in runs if r.started_at is not None), key=lambda r: r.started_at or datetime.min)
    days = sorted({_day(r) for r in dated})
    points = []
    seen: set[str] = set()
    for day in days:
        upto = [r for r in dated if _day(r) <= day]
        report = build_report(catalog, upto, filters)
        labels = ["/".join(part or "-" for part in context_key(run.context)) for run in report.snapshot]
        added = tuple(label for label in labels if label not in seen) if seen else ()
        seen.update(labels)
        statuses: dict[str, int] = {}
        for status in report.requirement_status.values():
            statuses[status] = statuses.get(status, 0) + 1
        points.append(
            DailyPoint(
                day=day,
                counts=report.outcome_counts,
                pass_rate=report.pass_rate,
                duration_seconds=sum(
                    r.duration_seconds or 0.0 for run in report.snapshot for r in run.results
                ),
                requirement_status=statuses,
                contexts=len(report.snapshot),
                carried=tuple(
                    "/".join(part or "-" for part in context_key(run.context))
                    for run in report.snapshot
                    if _day(run) < day
                ),
                added=added,
            )
        )
    return points


def coverage_snapshot(catalog: Catalog, name: str, taken_at: datetime | None = None) -> CoverageSnapshot:
    """The catalog's coverage now; the hash identifies the catalog's content, not its formatting."""
    totals = analyse_coverage(catalog).totals
    content = catalog.model_dump_json(exclude={"warnings"}).encode()
    return CoverageSnapshot(
        taken_at=taken_at or datetime.now(UTC),
        catalog=name,
        catalog_sha256=hashlib.sha256(content).hexdigest(),
        requirements=len(catalog.requirements),
        requirement_coverage=totals.requirement_coverage,
        automation_coverage=totals.automation_coverage,
        automated_requirement_coverage=totals.automated_requirement_coverage,
    )


def coverage_changes(snapshots: Sequence[CoverageSnapshot]) -> list[str]:
    """Plain-language notes about a coverage series (too few points to call it a trend)."""
    if not snapshots:
        return ["no coverage snapshot recorded yet: run `qi history import ... --catalog <catalog>`"]
    if len(snapshots) == 1:
        return [
            "one coverage snapshot so far: a trend needs the catalog to be recorded again after it changes"
        ]
    return []


def _day(run: TestRun) -> date:
    """UTC start date of a run (callers pass dated runs only)."""
    started = run.started_at or datetime.min.replace(tzinfo=UTC)
    return started.astimezone(UTC).date()


@dataclass(frozen=True)
class RepositorySnapshot:
    """One repository's snapshot at the end of a day: the latest run of each of its suites."""

    day: date
    results: int
    failed: int
    pass_rate: Ratio
    suites: int
    latest_run_id: str | None


@dataclass(frozen=True)
class RepositoryTrend:
    """A repository now and ``days`` earlier, with the tests whose failing state changed.

    Attributes:
        before: ``None`` when the repository had no run yet at that time.
        newly_failing: Test keys failing now in any suite that failed in none before.
        fixed: Test keys failing before in some suite that fail in none now.
    """

    repository: str
    now: RepositorySnapshot
    before: RepositorySnapshot | None
    newly_failing: tuple[str, ...]
    fixed: tuple[str, ...]


def repository_trends(
    runs: Iterable[TestRun], days: int = 7
) -> tuple[date | None, tuple[RepositoryTrend, ...]]:
    """Each repository's snapshot on the newest day with runs against ``days`` earlier.

    Only dated runs of a pipeline with a recorded repository take part. The newest day is the
    newest run's UTC date across all of them (the history's, not the clock's), the same for every
    repository, so the two columns are always the same two days. Repositories with new failures
    come first, then the largest drop in pass rate, then by name.
    """
    chosen = [r for r in runs if r.started_at is not None and r.pipeline and r.pipeline.repository]
    if not chosen:
        return None, ()
    today = max(_day(r) for r in chosen)
    earlier = today - timedelta(days=days)
    found = []
    for repository in sorted({r.pipeline.repository for r in chosen if r.pipeline and r.pipeline.repository}):
        own = [r for r in chosen if r.pipeline and r.pipeline.repository == repository]
        now, now_failing = _repository_snapshot(own, today)
        if now is None:
            continue
        before, before_failing = _repository_snapshot(own, earlier)
        found.append(
            RepositoryTrend(
                repository=repository,
                now=now,
                before=before,
                newly_failing=tuple(sorted(now_failing - before_failing)),
                fixed=tuple(sorted(before_failing - now_failing)),
            )
        )

    def drop(trend: RepositoryTrend) -> float:
        """Pass-rate points lost since ``before`` (0 when either side has no rate)."""
        if trend.before is None or trend.before.pass_rate.value is None or trend.now.pass_rate.value is None:
            return 0.0
        return trend.before.pass_rate.value - trend.now.pass_rate.value

    found.sort(key=lambda t: (not t.newly_failing, -drop(t), t.repository))
    return today, tuple(found)


def _repository_snapshot(runs: Sequence[TestRun], day: date) -> tuple[RepositorySnapshot | None, set[str]]:
    """The snapshot of these runs at the end of ``day`` and its failing test keys."""
    snapshot = latest_runs(r for r in runs if _day(r) <= day)
    if not snapshot:
        return None, set()
    counts = dict.fromkeys(Outcome, 0)
    failing: set[str] = set()
    for run in snapshot:
        for outcome, n in run.outcome_counts().items():
            counts[outcome] += n
        failing.update(r.key for r in run.results if r.outcome in (Outcome.FAILED, Outcome.ERROR))
    newest = max(snapshot, key=lambda r: r.started_at or datetime.min.replace(tzinfo=UTC))
    return (
        RepositorySnapshot(
            day=day,
            results=sum(counts.values()),
            failed=counts[Outcome.FAILED] + counts[Outcome.ERROR],
            pass_rate=execution_pass_rate(counts),
            suites=len(snapshot),
            latest_run_id=newest.run_id,
        ),
        failing,
    )
