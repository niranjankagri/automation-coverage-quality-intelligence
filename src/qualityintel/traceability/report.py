"""Traceability report: catalog coverage joined with execution results.

Which runs count (docs/metrics.md, "Execution status"): for every *run context* (framework,
environment, browser, platform; the build is not part of it) only the **latest** run is used,
so a re-run replaces the attempt before it and an old nightly does not hide today's result.
This set is called the *snapshot*. Older runs are history (Milestone 6).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime

from qualityintel.models.catalog import Catalog, TestCase
from qualityintel.models.enums import AutomationStatus, Criticality, Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import RunContext, TestRun
from qualityintel.traceability.coverage import CoverageReport, Filters, analyse_coverage
from qualityintel.traceability.matching import Execution, Matching, match_results

PASSING = "passing"
FAILING = "failing"
SKIPPED = "skipped"
NOT_RUN = "not run"
NOT_AUTOMATED = "not automated"


@dataclass(frozen=True)
class RunFilters:
    """Which runs are analysed; empty = all. Values compare with the run context.

    ``since`` and ``until`` are inclusive UTC dates of the run's start; when either is set,
    runs without a start time are left out (their date is unknown).
    """

    frameworks: frozenset[str] = frozenset()
    environments: frozenset[str] = frozenset()
    browsers: frozenset[str] = frozenset()
    platforms: frozenset[str] = frozenset()
    builds: frozenset[str] = frozenset()
    repositories: frozenset[str] = frozenset()
    since: date | None = None
    until: date | None = None

    def keeps(self, run: TestRun) -> bool:
        """True when every chosen dimension matches the run's context and date."""
        context = run.context
        if self.since is not None or self.until is not None:
            if run.started_at is None:
                return False
            day = run.started_at.astimezone(UTC).date()
            if (self.since is not None and day < self.since) or (self.until is not None and day > self.until):
                return False
        return all(
            not chosen or value in chosen
            for chosen, value in (
                (self.frameworks, context.framework),
                (self.environments, context.environment),
                (self.browsers, context.browser),
                (self.platforms, context.platform),
                (self.builds, context.build),
                (self.repositories, run.pipeline.repository if run.pipeline else None),
            )
        )


@dataclass(frozen=True)
class CaseExecution:
    """Execution status of one test case in the snapshot."""

    case: TestCase
    status: str
    executions: tuple[Execution, ...]


@dataclass
class TraceabilityReport:
    """Coverage plus execution status per test case and requirement.

    Attributes:
        snapshot: The latest run of each run context, oldest first.
        cases: Status per test case id (automated cases only have run statuses).
        requirement_status: ``passing``, ``failing``, ``skipped``, ``not run`` or
            ``not automated`` per in-scope requirement id.
        unmatched: Snapshot executions that belong to no test case.
    """

    coverage: CoverageReport
    snapshot: tuple[TestRun, ...]
    cases: dict[str, CaseExecution]
    requirement_status: dict[str, str]
    unmatched: tuple[Execution, ...]
    automated_cases_without_results: tuple[str, ...]
    unknown_ids: dict[str, int] = field(default_factory=dict)

    @property
    def outcome_counts(self) -> dict[Outcome, int]:
        """Outcomes of every result in the snapshot (matched or not)."""
        counts = dict.fromkeys(Outcome, 0)
        for run in self.snapshot:
            for outcome, count in run.outcome_counts().items():
                counts[outcome] += count
        return counts

    @property
    def pass_rate(self) -> Ratio:
        """Execution pass rate of the snapshot (docs/metrics.md, section 4)."""
        return execution_pass_rate(self.outcome_counts)

    @property
    def failing_critical(self) -> tuple[str, ...]:
        """Critical in-scope requirements whose automated tests fail in the snapshot."""
        return tuple(
            row.requirement.id
            for row in self.coverage.requirements
            if row.requirement.criticality is Criticality.CRITICAL
            and self.requirement_status[row.requirement.id] == FAILING
        )


def context_key(context: RunContext) -> tuple[str | None, ...]:
    """Identity of a run context for "latest run" and comparisons (build excluded)."""
    return (context.framework, context.environment, context.browser, context.platform)


def snapshot_key(run: TestRun) -> tuple[str | None, ...]:
    """What "the same suite" means for the snapshot: the run context, plus the pipeline job.

    Two jobs of a pipeline can share a context (component tests and UI tests, both in Chrome);
    they are different suites, so neither may replace the other.
    """
    return (*context_key(run.context), run.pipeline.job if run.pipeline else None)


def latest_runs(runs: Iterable[TestRun]) -> tuple[TestRun, ...]:
    """The newest run per run context (and pipeline job), ordered by start time.

    Runs without a start time sort before every dated run, so a dated run always wins; among
    undated runs the last one given wins (import order).
    """
    latest: dict[tuple[str | None, ...], TestRun] = {}
    for run in runs:
        key = snapshot_key(run)
        current = latest.get(key)
        if current is None or _when(run) >= _when(current):
            latest[key] = run
    return tuple(sorted(latest.values(), key=lambda r: (_when(r), r.source)))


def build_report(
    catalog: Catalog,
    runs: Iterable[TestRun],
    filters: Filters | None = None,
    run_filters: RunFilters | None = None,
    one_execution: bool = False,
) -> TraceabilityReport:
    """Join catalog coverage with the snapshot of the given runs.

    Args:
        catalog: Requirements and test cases.
        runs: Runs to take the snapshot from.
        filters: Catalog scope (all when omitted).
        run_filters: Run scope (all when omitted).
        one_execution: The runs are one execution (the jobs of one pipeline execution): every
            run counts. Otherwise the snapshot is the latest run per context and job.
    """
    coverage = analyse_coverage(catalog, filters)
    chosen = [run for run in runs if (run_filters or RunFilters()).keeps(run)]
    snapshot = (
        tuple(sorted(chosen, key=lambda r: (_when(r), r.source))) if one_execution else latest_runs(chosen)
    )
    matching = match_results(catalog, snapshot)

    in_scope = {case.id for row in coverage.requirements for case in row.test_cases} | {
        case.id for case in coverage.unlinked_automated_cases
    }
    cases = {case.id: _case_execution(case, matching) for case in catalog.test_cases if case.id in in_scope}
    requirement_status = {
        row.requirement.id: _requirement_status([cases[c.id] for c in row.test_cases])
        for row in coverage.requirements
    }
    return TraceabilityReport(
        coverage=coverage,
        snapshot=snapshot,
        cases=cases,
        requirement_status=requirement_status,
        unmatched=tuple(matching.unmatched),
        automated_cases_without_results=tuple(
            case_id for case_id in matching.automated_cases_without_results(catalog) if case_id in in_scope
        ),
        unknown_ids=dict(matching.unknown_ids),
    )


def _case_execution(case: TestCase, matching: Matching) -> CaseExecution:
    """Status of one case from its snapshot executions.

    failing: any execution failed or errored; passing: at least one passed and none failed;
    skipped: every execution was skipped; not run: no execution; not automated: manual,
    planned or blocked.
    """
    executions = tuple(matching.by_case.get(case.id, ()))
    if case.automation_status is not AutomationStatus.AUTOMATED:
        return CaseExecution(case, NOT_AUTOMATED, executions)
    outcomes = {e.result.outcome for e in executions}
    if not outcomes:
        status = NOT_RUN
    elif outcomes & {Outcome.FAILED, Outcome.ERROR}:
        status = FAILING
    elif Outcome.PASSED in outcomes:
        status = PASSING
    else:
        status = SKIPPED
    return CaseExecution(case, status, executions)


def _requirement_status(cases: list[CaseExecution]) -> str:
    """Worst status of the automated cases: failing > not run > skipped > passing.

    "not run" ranks above "passing" on purpose: if one automated case of a requirement did
    not run, the requirement is not fully verified even though another case passed.
    """
    automated = [c.status for c in cases if c.status != NOT_AUTOMATED]
    if not automated:
        return NOT_AUTOMATED
    for status in (FAILING, NOT_RUN, SKIPPED):
        if status in automated:
            return status
    return PASSING


def _when(run: TestRun) -> datetime:
    """Sort key: start time, undated runs first."""
    return run.started_at or datetime.min.replace(tzinfo=UTC)
