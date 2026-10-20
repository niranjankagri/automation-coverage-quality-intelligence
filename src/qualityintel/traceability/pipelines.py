"""Group runs into pipeline executions (docs/pipelines.md).

A CI pipeline execution has several jobs; each job imports its own result files as runs with
the same ``pipeline_id`` (:class:`~qualityintel.models.results.PipelineJob`). This module puts
them back together and says whether the execution is **complete**: a release decision on a
pipeline whose UI job was cancelled would otherwise rest on the API results alone.

Rules:

- a job's highest attempt replaces its earlier attempts (a re-run job counts once);
- a pipeline is complete when every expected job reported runs with at least one result, and
  all its runs agree on branch and commit;
- anything else is incomplete, with one problem per reason. Unexpected extra jobs are listed
  but do not make it incomplete.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from qualityintel.models.enums import Outcome
from qualityintel.models.results import TestRun


class PipelineState(StrEnum):
    """Whether a pipeline execution can support a decision."""

    COMPLETE = "complete"
    INCOMPLETE = "incomplete"


@dataclass(frozen=True)
class JobReport:
    """What one job of a pipeline execution reported (its highest attempt).

    Attributes:
        expected: True when the job is one of the expected jobs (or none were given).
        superseded: Runs of earlier attempts of this job, which no longer count.
    """

    name: str
    attempt: int
    runs: tuple[TestRun, ...]
    expected: bool = True
    superseded: tuple[TestRun, ...] = ()

    @property
    def result_count(self) -> int:
        """Number of test results in the counted runs."""
        return sum(len(run.results) for run in self.runs)

    @property
    def outcome_counts(self) -> dict[Outcome, int]:
        """Results per outcome over the counted runs."""
        counts = dict.fromkeys(Outcome, 0)
        for run in self.runs:
            for outcome, n in run.outcome_counts().items():
                counts[outcome] += n
        return counts


@dataclass(frozen=True)
class PipelineExecution:
    """One pipeline execution with its jobs and, if any, why it is incomplete."""

    pipeline_id: str
    branch: str | None
    commit: str | None
    jobs: tuple[JobReport, ...]
    missing: tuple[str, ...]
    problems: tuple[str, ...]

    @property
    def state(self) -> PipelineState:
        """Complete only without any problem."""
        return PipelineState.INCOMPLETE if self.problems else PipelineState.COMPLETE

    @property
    def runs(self) -> list[TestRun]:
        """The runs that count: highest attempt of every job."""
        return [run for job in self.jobs for run in job.runs]


def pipeline_execution(
    runs: Iterable[TestRun], pipeline_id: str, expected_jobs: Sequence[str] = ()
) -> PipelineExecution:
    """The execution ``pipeline_id`` as reported by ``runs`` (other runs are ignored).

    Args:
        runs: Runs to look in, from files or history.
        pipeline_id: Pipeline execution to assemble.
        expected_jobs: Jobs that must report for the execution to be complete. Empty: the jobs
            found are taken as the whole pipeline (only consistency is checked).
    """
    attempts: dict[str, dict[int, list[TestRun]]] = {}
    for run in runs:
        if run.pipeline is not None and run.pipeline.pipeline_id == pipeline_id:
            attempts.setdefault(run.pipeline.job, {}).setdefault(run.pipeline.attempt, []).append(run)

    expected = tuple(dict.fromkeys(expected_jobs))
    jobs = []
    for name in sorted(
        attempts, key=lambda n: (n not in expected, expected.index(n) if n in expected else 0, n)
    ):
        by_attempt = attempts[name]
        latest = max(by_attempt)
        jobs.append(
            JobReport(
                name=name,
                attempt=latest,
                runs=tuple(by_attempt[latest]),
                expected=not expected or name in expected,
                superseded=tuple(
                    run for attempt in sorted(by_attempt) if attempt < latest for run in by_attempt[attempt]
                ),
            )
        )

    problems: list[str] = []
    missing = tuple(name for name in expected if name not in attempts)
    if not attempts:
        problems.append(f"pipeline {pipeline_id}: no runs of this pipeline were read")
    for name in missing:
        problems.append(
            f"pipeline {pipeline_id}: job {name} reported no results (not run, cancelled or interrupted)"
        )
    for job in jobs:
        if job.expected and job.result_count == 0:
            problems.append(f"pipeline {pipeline_id}: job {job.name} reported runs without any test result")
    counted = [run for job in jobs if job.expected for run in job.runs]
    branch = _agreed(counted, "branch", pipeline_id, problems)
    commit = _agreed(counted, "commit", pipeline_id, problems)
    return PipelineExecution(
        pipeline_id=pipeline_id,
        branch=branch,
        commit=commit,
        jobs=tuple(jobs),
        missing=missing,
        problems=tuple(problems),
    )


def pipeline_ids(runs: Iterable[TestRun]) -> list[str]:
    """Pipeline ids found in the runs, in order of first appearance."""
    return list(dict.fromkeys(run.pipeline.pipeline_id for run in runs if run.pipeline is not None))


def _agreed(runs: list[TestRun], field: str, pipeline_id: str, problems: list[str]) -> str | None:
    """The one value of ``branch``/``commit`` that the runs record; a problem if they disagree."""
    jobs_by_value: dict[str, set[str]] = {}
    for run in runs:
        value = getattr(run.pipeline, field) if run.pipeline is not None else None
        if value is not None and run.pipeline is not None:
            jobs_by_value.setdefault(value, set()).add(run.pipeline.job)
    if len(jobs_by_value) > 1:
        listed = ", ".join(
            f"{value} ({', '.join(sorted(jobs))})" for value, jobs in sorted(jobs_by_value.items())
        )
        problems.append(f"pipeline {pipeline_id}: jobs disagree on the {field}: {listed}")
        return None
    return next(iter(jobs_by_value), None)
