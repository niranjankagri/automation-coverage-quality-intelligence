"""The release gate over time: its verdict on each day's snapshot and the days it changed.

Each day uses the same end-of-day snapshot as the Trends page (``history/trends.py``): the latest
run of every suite started on or before that day. The gate is evaluated on that snapshot exactly
as ``qi gate`` would evaluate it; the readiness warnings (flaky candidates, collections,
freshness) are not part of the gate and not part of this history.

A **change** is a day whose verdict differs from the previous day's, or whose set of failing rules
differs (a gate can stay failed while the reason changes). The catalog is today's: a requirement
added today counts as a gap on earlier days too (docs/quality-gates.md, "Gate history").
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from itertools import pairwise

from qualityintel.gates.config import GateConfig
from qualityintel.gates.evaluate import GateStatus, evaluate
from qualityintel.models.catalog import Catalog
from qualityintel.models.results import TestRun
from qualityintel.traceability.coverage import Filters
from qualityintel.traceability.report import RunFilters, build_report


@dataclass(frozen=True)
class GateDay:
    """The gate's verdict on one day's snapshot.

    Attributes:
        failed_rules: Names of the rules that make the gate fail (empty when it passed).
        latest_run_id: The newest run in that day's snapshot, as evidence.
    """

    day: date
    status: GateStatus
    failed_rules: tuple[str, ...]
    input_problems: tuple[str, ...]
    results: int
    latest_run_id: str | None


@dataclass(frozen=True)
class GateChange:
    """A day on which the verdict or the failing rules changed."""

    day: date
    previous: GateStatus
    status: GateStatus
    started_failing: tuple[str, ...]
    stopped_failing: tuple[str, ...]


def gate_history(
    runs: Iterable[TestRun],
    catalog: Catalog,
    gate: GateConfig,
    filters: Filters | None = None,
    run_filters: RunFilters | None = None,
    days: int = 30,
) -> tuple[tuple[GateDay, ...], tuple[GateChange, ...]]:
    """The gate on each of the last ``days`` days with runs (oldest first) and its changes.

    Undated runs are left out (they cannot be placed on a day). The first day listed has no
    previous day, so it is never a change.
    """
    chosen = [r for r in runs if r.started_at is not None and (run_filters or RunFilters()).keeps(r)]
    all_days = sorted({_day(r) for r in chosen})[-days:]
    history = []
    for day in all_days:
        upto = [r for r in chosen if _day(r) <= day]
        report = build_report(catalog, upto, filters)
        result = evaluate(report, gate)
        newest = max(
            report.snapshot, key=lambda r: r.started_at or datetime.min.replace(tzinfo=UTC), default=None
        )
        history.append(
            GateDay(
                day=day,
                status=result.status,
                failed_rules=tuple(rule.name for rule in result.failed_rules),
                input_problems=tuple(result.input_problems),
                results=sum(report.outcome_counts.values()),
                latest_run_id=newest.run_id if newest else None,
            )
        )
    changes = []
    for before, after in pairwise(history):
        if before.status is after.status and before.failed_rules == after.failed_rules:
            continue
        changes.append(
            GateChange(
                day=after.day,
                previous=before.status,
                status=after.status,
                started_failing=tuple(r for r in after.failed_rules if r not in before.failed_rules),
                stopped_failing=tuple(r for r in before.failed_rules if r not in after.failed_rules),
            )
        )
    return tuple(history), tuple(changes)


def _day(run: TestRun) -> date:
    """UTC start date of a dated run."""
    started = run.started_at or datetime.min.replace(tzinfo=UTC)
    return started.astimezone(UTC).date()
