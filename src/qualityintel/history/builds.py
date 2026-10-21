"""Compare two builds (docs/history.md, "Comparing builds").

A build is every run whose context names it (``build``: the commit or version tested). Within each
build the latest run per context and pipeline job counts, as in the snapshot. Two builds are only
compared where they ran the same suite in the same place (same context and job): those pairs are
compared test by test with :func:`compare_runs`; every other context is listed as incomparable,
never counted as a change.

"Newly flaky" is the stability classification of the history up to each build's last run: a
test that is a flaky candidate up to the head build but was not up to the base build.
Coverage is taken from the latest recorded coverage snapshot before each build's last run; when
there is none, that is said instead of guessing.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from qualityintel.history.analysis import (
    DEFAULTS,
    HistorySettings,
    RunComparison,
    Stability,
    compare_runs,
    stability_report,
)
from qualityintel.history.trends import CoverageSnapshot
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import TestRun
from qualityintel.traceability.report import context_key, latest_runs, snapshot_key


@dataclass(frozen=True)
class BuildSide:
    """One build: its counted runs and their totals."""

    build: str
    runs: tuple[TestRun, ...]
    counts: dict[Outcome, int]
    pass_rate: Ratio
    last_started_at: datetime | None
    coverage: CoverageSnapshot | None


@dataclass(frozen=True)
class ContextComparison:
    """The comparison of one suite (context and job) between the two builds."""

    label: str
    base_run: TestRun
    head_run: TestRun
    changes: RunComparison


@dataclass(frozen=True)
class BuildComparison:
    """Two builds side by side and what changed between them where they are comparable."""

    base: BuildSide
    head: BuildSide
    compared: tuple[ContextComparison, ...]
    only_in_base: tuple[str, ...]
    only_in_head: tuple[str, ...]
    newly_flaky: tuple[tuple[str, str], ...] = field(default=())

    @property
    def comparable(self) -> bool:
        """At least one suite ran in both builds."""
        return bool(self.compared)


def label(run: TestRun) -> str:
    """``framework / environment / browser / platform`` plus the pipeline job, '-' for missing parts."""
    parts = "/".join(part or "-" for part in context_key(run.context))
    return f"{parts} ({run.pipeline.job})" if run.pipeline else parts


def builds_in_order(runs: Iterable[TestRun]) -> list[str]:
    """Builds by the start of their first run; builds without any dated run last, by name."""
    first: dict[str, datetime] = {}
    undated: set[str] = set()
    for run in runs:
        build = run.context.build
        if build is None:
            continue
        if run.started_at is None:
            undated.add(build)
        elif build not in first or run.started_at < first[build]:
            first[build] = run.started_at
    dated = sorted(first, key=lambda b: (first[b], b))
    return [*dated, *sorted(undated - first.keys())]


def _compare_key(run: TestRun) -> tuple[str | None, ...]:
    """The suite, and for a pipeline job also the result file inside it.

    A job may write one file per test class; each file is compared with the same file of the
    other build.
    """
    return (*snapshot_key(run), run.source if run.pipeline else None)


def _pair_labels(runs: Iterable[TestRun]) -> dict[str, str]:
    """Label per run id; runs sharing a label (files of one job) also name their file."""
    chosen = list(runs)
    counts: dict[str, int] = {}
    for run in chosen:
        counts[label(run)] = counts.get(label(run), 0) + 1
    return {
        run.run_id: label(run)
        if counts[label(run)] == 1
        else f"{label(run)} · {run.source.rsplit('/', 1)[-1]}"
        for run in chosen
    }


def compare_builds(
    runs: Sequence[TestRun],
    base: str,
    head: str,
    snapshots: Sequence[CoverageSnapshot] = (),
    settings: HistorySettings = DEFAULTS,
) -> BuildComparison:
    """Compare build ``base`` with build ``head`` over ``runs`` (``KeyError`` if a build has no runs)."""
    base_side = _side(runs, base, snapshots)
    head_side = _side(runs, head, snapshots)
    base_by_key = {_compare_key(run): run for run in base_side.runs}
    head_by_key = {_compare_key(run): run for run in head_side.runs}
    common = base_by_key.keys() & head_by_key.keys()
    names = _pair_labels(head_by_key[key] for key in common)
    compared = tuple(
        ContextComparison(
            names[head_by_key[key].run_id],
            base_by_key[key],
            head_by_key[key],
            compare_runs(base_by_key[key], head_by_key[key], settings),
        )
        for key in sorted(common, key=lambda k: (names[head_by_key[k].run_id], str(k)))
    )
    return BuildComparison(
        base=base_side,
        head=head_side,
        compared=compared,
        only_in_base=tuple(sorted(label(base_by_key[k]) for k in base_by_key.keys() - head_by_key.keys())),
        only_in_head=tuple(sorted(label(head_by_key[k]) for k in head_by_key.keys() - base_by_key.keys())),
        newly_flaky=_newly_flaky(runs, base_side, head_side, settings),
    )


def _side(runs: Sequence[TestRun], build: str, snapshots: Sequence[CoverageSnapshot]) -> BuildSide:
    """The counted runs of one build and their totals."""
    chosen = latest_runs(run for run in runs if run.context.build == build)
    if not chosen:
        raise KeyError(build)
    counts = dict.fromkeys(Outcome, 0)
    for run in chosen:
        for outcome, n in run.outcome_counts().items():
            counts[outcome] += n
    starts = [run.started_at for run in chosen if run.started_at is not None]
    last = max(starts, default=None)
    before = [s for s in snapshots if last is not None and s.taken_at <= last]
    return BuildSide(
        build=build,
        runs=tuple(chosen),
        counts=counts,
        pass_rate=execution_pass_rate(counts),
        last_started_at=last,
        coverage=max(before, key=lambda s: s.taken_at) if before else None,
    )


def _newly_flaky(
    runs: Sequence[TestRun], base: BuildSide, head: BuildSide, settings: HistorySettings
) -> tuple[tuple[str, str], ...]:
    """Flaky candidates in the history up to the head build that were not up to the base build."""
    if base.last_started_at is None or head.last_started_at is None:
        return ()

    def flaky(until: datetime) -> set[tuple[str, str]]:
        history = [run for run in runs if run.started_at is not None and run.started_at <= until]
        return {
            (row.key, "/".join(part or "-" for part in row.context))
            for row in stability_report(history, settings)
            if row.status is Stability.FLAKY_CANDIDATE
        }

    return tuple(sorted(flaky(head.last_started_at) - flaky(base.last_started_at)))
