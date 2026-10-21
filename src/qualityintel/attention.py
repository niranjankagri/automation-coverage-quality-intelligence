"""The evidence rules behind *Needs attention* (docs/attention.md).

A finding says what the records show, never more: **open** only when the latest evidence still
shows the problem, **resolved** when later evidence shows it gone (kept as a historical
observation), **suspected** for flaky candidates (flakiness is a suspicion, never proven by a
pattern), **unknown** when there is not enough evidence to say.

The pure functions here work on runs and collection records; the workspace adds the analyses it
already has (stability, recurring failures, duration regressions, coverage gaps, collection
freshness) and turns everything into findings with links.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from qualityintel.models.collection import PipelineCollection
from qualityintel.models.enums import Outcome
from qualityintel.models.results import TestResult, TestRun
from qualityintel.traceability.report import snapshot_key

OPEN = "open"
RESOLVED = "resolved"
SUSPECTED = "suspected"
UNKNOWN = "unknown"
FAILING = (Outcome.FAILED, Outcome.ERROR)
_EPOCH = datetime.min.replace(tzinfo=UTC)

# Severity, most urgent first (documented in docs/attention.md): a test that broke in the latest
# execution, then evidence that is missing, then gaps and recurring problems, then signals that
# need more observation.
SEVERITY = {
    "newly failing": 1,
    "incomplete pipeline": 2,
    "critical gap": 3,
    "recurring failure": 4,
    "duration regression": 5,
    "flaky candidate": 6,
    "overdue collection": 7,
}


@dataclass(frozen=True)
class Execution:
    """All runs of one execution of a suite: a pipeline job attempt, or one run outside pipelines."""

    suite: tuple[str | None, ...]
    runs: tuple[TestRun, ...]

    @property
    def started_at(self) -> datetime | None:
        """The latest start among its runs."""
        starts = [r.started_at for r in self.runs if r.started_at is not None]
        return max(starts, default=None)

    def results(self) -> dict[str, tuple[TestRun, TestResult]]:
        """The result of every test key in the execution (the last one wins, as in a run)."""
        return {result.key: (run, result) for run in self.runs for result in run.results}


@dataclass(frozen=True)
class NewlyFailing:
    """A test that failed in the latest execution of its suite and passed in the one before."""

    key: str
    latest_run: TestRun
    latest: TestResult
    previous_run: TestRun


@dataclass(frozen=True)
class PipelineState:
    """The latest collected attempt of a pipeline and whether a later complete one resolved it."""

    record: PipelineCollection
    state: str
    resolved_by: PipelineCollection | None


def executions(runs: Iterable[TestRun]) -> dict[tuple[str | None, ...], list[Execution]]:
    """The executions of every suite (as in the snapshot), oldest first."""
    grouped: dict[tuple[str | None, ...], dict[tuple[str, ...], list[TestRun]]] = {}
    for run in runs:
        execution = (run.pipeline.pipeline_id, str(run.pipeline.attempt)) if run.pipeline else (run.run_id,)
        grouped.setdefault(snapshot_key(run), {}).setdefault(execution, []).append(run)
    return {
        suite: sorted(
            (Execution(suite, tuple(group)) for group in by_execution.values()),
            key=lambda e: (e.started_at or _EPOCH, e.runs[0].source),
        )
        for suite, by_execution in grouped.items()
    }


def newly_failing(runs: Iterable[TestRun]) -> list[NewlyFailing]:
    """Tests failing in the latest execution of their suite that passed in the previous one.

    A test new in the latest execution is not *newly failing* (nothing to compare with); a re-run
    attempt that passed is a newer execution, so a failure fixed by a re-run is not listed.
    """
    found: list[NewlyFailing] = []
    for suite_executions in executions(runs).values():
        if len(suite_executions) < 2:
            continue
        latest, previous = suite_executions[-1].results(), suite_executions[-2].results()
        for key, (run, result) in sorted(latest.items()):
            before = previous.get(key)
            if result.outcome in FAILING and before is not None and before[1].outcome is Outcome.PASSED:
                found.append(NewlyFailing(key, run, result, before[0]))
    return found


def latest_outcomes(runs: Iterable[TestRun]) -> dict[str, tuple[Outcome, datetime | None]]:
    """Each test key's outcome in its latest execution (over every suite it runs in)."""
    latest: dict[str, tuple[Outcome, datetime | None]] = {}
    for suite_executions in executions(runs).values():
        execution = suite_executions[-1]
        for key, (_, result) in execution.results().items():
            when = execution.started_at
            current = latest.get(key)
            if current is None or (when or _EPOCH) >= (current[1] or _EPOCH):
                latest[key] = (result.outcome, when)
    return latest


def pipeline_states(records: Sequence[PipelineCollection]) -> list[PipelineState]:
    """Incomplete pipelines, each open unless a later complete run of its workflow resolved it."""
    by_workflow: dict[tuple[str, str], list[PipelineCollection]] = {}
    for record in records:
        by_workflow.setdefault((record.repository, record.workflow), []).append(record)
    states: list[PipelineState] = []
    for group in by_workflow.values():
        ordered = sorted(group, key=lambda r: (r.started_at or r.collected_at, r.attempt))
        for index, record in enumerate(ordered):
            if record.state != "incomplete":
                continue
            later = next((r for r in ordered[index + 1 :] if r.state == "complete"), None)
            states.append(PipelineState(record, RESOLVED if later else OPEN, later))
    return states


def recurring_state(tests: Iterable[str], latest: dict[str, tuple[Outcome, datetime | None]]) -> str:
    """Open while any of the tests still fails in its latest execution; resolved when all pass."""
    outcomes = [latest[key][0] for key in tests if key in latest]
    if not outcomes:
        return UNKNOWN
    if any(outcome in FAILING for outcome in outcomes):
        return OPEN
    return RESOLVED if all(outcome is Outcome.PASSED for outcome in outcomes) else UNKNOWN
