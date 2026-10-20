"""Read-only queries over one catalog and a set of runs, shaped for the dashboard and its API.

This module holds the logic behind every dashboard view (what is counted, in which order,
what "latest" means), so it is tested without a server or a browser. The dashboard package
only turns these view models into JSON and HTML.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from qualityintel.history.analysis import (
    DEFAULTS,
    HistorySettings,
    Stability,
    duration_regressions,
    recurring_failures,
    stability_report,
    trend,
)
from qualityintel.ingest.batch import Batch, import_results
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.models.catalog import Catalog, Requirement
from qualityintel.models.enums import AutomationStatus, Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import RunContext, TestResult, TestRun
from qualityintel.traceability.coverage import UNSPECIFIED, Filters
from qualityintel.traceability.matching import match_results
from qualityintel.traceability.report import RunFilters, TraceabilityReport, build_report


class View(BaseModel):
    """Base for view models: immutable, serialisable to JSON."""

    model_config = ConfigDict(frozen=True)


class RatioView(View):
    """A metric as the dashboard shows it."""

    numerator: int
    denominator: int
    percent: float | None
    text: str

    @classmethod
    def of(cls, ratio: Ratio) -> RatioView:
        """Copy a :class:`Ratio` with its display text."""
        return cls(
            numerator=ratio.numerator, denominator=ratio.denominator, percent=ratio.percent, text=str(ratio)
        )


class RunView(View):
    """One imported run, without its results."""

    run_id: str
    source: str
    context: RunContext
    started_at: datetime | None
    counts: dict[Outcome, int]
    pass_rate: RatioView


class FailureView(View):
    """Failure details of one execution."""

    message: str
    type: str
    text: str


class ExecutionView(View):
    """One execution of one test, with the run it belongs to."""

    key: str
    name: str
    outcome: Outcome
    duration_seconds: float | None
    retries: int
    failure: FailureView | None
    run_id: str
    source: str
    started_at: datetime | None
    context: RunContext


class RequirementRow(View):
    """A requirement in lists."""

    id: str
    title: str
    feature: str
    criticality: str
    priority: str
    risk: str
    platforms: tuple[str, ...]
    test_cases: int
    automated_test_cases: int
    coverage_status: str
    execution_status: str


class TestCaseView(View):
    """A linked test case with its snapshot executions."""

    __test__ = False  # not a pytest test class, despite the name

    id: str
    title: str
    automation_status: str
    test_type: str
    framework: str
    execution_status: str
    executions: tuple[ExecutionView, ...]


class RequirementDetail(View):
    """One requirement, its test cases and their latest executions."""

    requirement: RequirementRow
    test_cases: tuple[TestCaseView, ...]


class Summary(View):
    """Top of the dashboard: coverage, gaps and the execution snapshot."""

    requirements_total: int
    requirements_with_tests: int
    requirements_without_tests: tuple[str, ...]
    requirements_without_automation: tuple[str, ...]
    uncovered_critical: tuple[RequirementRow, ...]
    unlinked_automated_cases: tuple[str, ...]
    requirement_coverage: RatioView
    automation_coverage: RatioView
    automated_requirement_coverage: RatioView
    snapshot: tuple[RunView, ...]
    outcome_counts: dict[Outcome, int]
    pass_rate: RatioView
    requirement_status_counts: dict[str, int]
    failing_requirements: tuple[RequirementRow, ...]
    failing_critical: tuple[str, ...]
    unmatched_results: int
    automated_cases_without_results: tuple[str, ...]


class TestRow(View):
    """One test (result key) across all analysed runs."""

    __test__ = False  # not a pytest test class, despite the name

    key: str
    name: str
    classname: str
    frameworks: tuple[str, ...]
    executions: int
    passed: int
    failed: int
    errors: int
    skipped: int
    latest_outcome: Outcome
    latest_started_at: datetime | None
    last_failure: str
    test_cases: tuple[str, ...]


class TestHistory(View):
    """Every execution of one test, newest first."""

    __test__ = False  # not a pytest test class, despite the name

    key: str
    test_cases: tuple[str, ...]
    executions: tuple[ExecutionView, ...]


class RunDetail(View):
    """One run with all of its results."""

    run: RunView
    executions: tuple[ExecutionView, ...]


class StabilityRow(View):
    """One test in one run context, classified from its history."""

    key: str
    context: str
    status: str
    verdicts: int
    failures: int
    failure_rate: RatioView
    reasons: tuple[str, ...]
    last_outcome: Outcome
    last_failure: str
    test_cases: tuple[str, ...]


class RecurringView(View):
    """A failure signature seen in several runs."""

    signature: str
    occurrences: int
    runs: int
    tests: tuple[str, ...]


class RegressionView(View):
    """A test that became clearly slower and stayed slower."""

    key: str
    context: str
    baseline_seconds: float
    latest_seconds: float
    baseline_runs: int


class TrendPoint(View):
    """One run in a context's trend."""

    run_id: str
    source: str
    started_at: datetime | None
    build: str | None
    pass_rate: RatioView
    failed: int


class StabilityView(View):
    """Everything the history analysis says about the chosen runs."""

    status_counts: dict[str, int]
    rows: tuple[StabilityRow, ...]
    recurring_failures: tuple[RecurringView, ...]
    duration_regressions: tuple[RegressionView, ...]
    trends: dict[str, tuple[TrendPoint, ...]]
    window: int


class Facets(View):
    """Filter values that exist in the data, for the dashboard's drop-downs."""

    features: tuple[str, ...]
    criticalities: tuple[str, ...]
    platforms: tuple[str, ...]
    test_types: tuple[str, ...]
    frameworks: tuple[str, ...]
    environments: tuple[str, ...]
    browsers: tuple[str, ...]


@dataclass(frozen=True)
class Scope:
    """Every filter the dashboard offers, in one object."""

    filters: Filters = field(default_factory=Filters)
    run_filters: RunFilters = field(default_factory=RunFilters)


# The default for every query: no filter at all (Scope is immutable, so one instance is safe)
EVERYTHING = Scope()


class Workspace:
    """A catalog and the runs imported for it."""

    def __init__(self, catalog: Catalog, runs: Iterable[TestRun]) -> None:
        self.catalog = catalog
        self.runs = tuple(sorted(runs, key=lambda r: (r.started_at is None, r.started_at, r.source)))
        self._runs_by_id = {run.run_id: run for run in self.runs}

    @classmethod
    def load(cls, catalog_path: Path, results: Sequence[str | Path]) -> tuple[Workspace, Batch]:
        """Load a catalog and result files; the batch tells about duplicates and errors."""
        batch = import_results(results) if results else Batch()
        return cls(load_catalog(catalog_path), batch.runs), batch

    # ---- views ---------------------------------------------------------------------------

    def facets(self) -> Facets:
        """Distinct filter values present in the catalog and the runs."""
        reqs, cases = self.catalog.requirements, self.catalog.test_cases
        return Facets(
            features=_sorted(r.feature or UNSPECIFIED for r in reqs),
            criticalities=_sorted(_text(r.criticality) for r in reqs),
            platforms=_sorted(p for r in reqs for p in (r.platforms or (UNSPECIFIED,))),
            test_types=_sorted(_text(c.test_type) for c in cases),
            frameworks=_sorted(
                [
                    *(c.framework for c in cases if c.framework),
                    *(r.context.framework for r in self.runs if r.context.framework),
                ]
            ),
            environments=_sorted(r.context.environment for r in self.runs if r.context.environment),
            browsers=_sorted(r.context.browser for r in self.runs if r.context.browser),
        )

    def summary(self, scope: Scope = EVERYTHING) -> Summary:
        """Coverage, gaps and snapshot numbers for the scope."""
        report = self._report(scope)
        coverage = report.coverage
        rows = {row.requirement.id: self._row(row.requirement, report) for row in coverage.requirements}
        status_counts: dict[str, int] = {}
        for status in report.requirement_status.values():
            status_counts[status] = status_counts.get(status, 0) + 1
        return Summary(
            requirements_total=len(coverage.requirements),
            requirements_with_tests=coverage.totals.requirement_coverage.numerator,
            requirements_without_tests=tuple(r.id for r in coverage.requirements_without_tests),
            requirements_without_automation=tuple(r.id for r in coverage.requirements_without_automation),
            uncovered_critical=tuple(rows[r.id] for r in coverage.uncovered_critical),
            unlinked_automated_cases=tuple(c.id for c in coverage.unlinked_automated_cases),
            requirement_coverage=RatioView.of(coverage.totals.requirement_coverage),
            automation_coverage=RatioView.of(coverage.totals.automation_coverage),
            automated_requirement_coverage=RatioView.of(coverage.totals.automated_requirement_coverage),
            snapshot=tuple(_run_view(run) for run in report.snapshot),
            outcome_counts=report.outcome_counts,
            pass_rate=RatioView.of(report.pass_rate),
            requirement_status_counts=status_counts,
            failing_requirements=tuple(
                row for rid, row in rows.items() if report.requirement_status[rid] == "failing"
            ),
            failing_critical=report.failing_critical,
            unmatched_results=len(report.unmatched),
            automated_cases_without_results=report.automated_cases_without_results,
        )

    def requirements(
        self, scope: Scope = EVERYTHING, status: str | None = None
    ) -> tuple[RequirementRow, ...]:
        """In-scope requirements; ``status`` keeps rows whose coverage or execution status matches."""
        report = self._report(scope)
        rows = tuple(self._row(row.requirement, report) for row in report.coverage.requirements)
        if status:
            rows = tuple(r for r in rows if status in (r.coverage_status, r.execution_status))
        return rows

    def requirement(self, requirement_id: str, scope: Scope = EVERYTHING) -> RequirementDetail:
        """One requirement with its linked cases (``KeyError`` if unknown)."""
        requirement = self.catalog.requirement(requirement_id)
        report = self._report(Scope(run_filters=scope.run_filters))
        cases = []
        for case in self.catalog.test_cases_for(requirement_id):
            execution = report.cases[case.id]
            cases.append(
                TestCaseView(
                    id=case.id,
                    title=case.title,
                    automation_status=case.automation_status.value,
                    test_type=_text(case.test_type),
                    framework=case.framework or UNSPECIFIED,
                    execution_status=execution.status,
                    executions=tuple(_execution_view(e.run, e.result) for e in execution.executions),
                )
            )
        return RequirementDetail(requirement=self._row(requirement, report), test_cases=tuple(cases))

    def tests(self, scope: Scope = EVERYTHING, outcome: Outcome | None = None) -> tuple[TestRow, ...]:
        """Every test key in the chosen runs; ``outcome`` keeps tests whose latest result has it."""
        runs = self._runs(scope)
        cases = self._case_ids_by_key(runs)
        grouped: dict[str, list[tuple[TestRun, TestResult]]] = {}
        for run in runs:
            for result in run.results:
                grouped.setdefault(result.key, []).append((run, result))
        rows = []
        for key, items in grouped.items():
            latest_run, latest = items[-1]  # runs are ordered by start time
            counts = {o: sum(1 for _, r in items if r.outcome is o) for o in Outcome}
            failures = [
                r.failure.message
                for _, r in items
                if r.failure and r.outcome in (Outcome.FAILED, Outcome.ERROR)
            ]
            rows.append(
                TestRow(
                    key=key,
                    name=latest.name,
                    classname=latest.classname,
                    frameworks=_sorted(run.context.framework or UNSPECIFIED for run, _ in items),
                    executions=len(items),
                    passed=counts[Outcome.PASSED],
                    failed=counts[Outcome.FAILED],
                    errors=counts[Outcome.ERROR],
                    skipped=counts[Outcome.SKIPPED],
                    latest_outcome=latest.outcome,
                    latest_started_at=latest_run.started_at,
                    last_failure=failures[-1] if failures else "",
                    test_cases=cases.get(key, ()),
                )
            )
        rows.sort(key=lambda r: (-(r.failed + r.errors), r.key))
        if outcome is not None:
            rows = [r for r in rows if r.latest_outcome is outcome]
        return tuple(rows)

    def test_history(self, key: str, scope: Scope = EVERYTHING) -> TestHistory:
        """All executions of one test key, newest first (``KeyError`` if it never ran)."""
        runs = self._runs(scope)
        executions = [_execution_view(run, r) for run in runs for r in run.results if r.key == key]
        if not executions:
            raise KeyError(key)
        return TestHistory(
            key=key,
            test_cases=self._case_ids_by_key(runs).get(key, ()),
            executions=tuple(reversed(executions)),
        )

    def run_list(self, scope: Scope = EVERYTHING) -> tuple[RunView, ...]:
        """Chosen runs, newest first."""
        return tuple(_run_view(run) for run in reversed(self._runs(scope)))

    def run(self, run_id: str) -> RunDetail:
        """One run with every result, failures first (``KeyError`` if unknown)."""
        run = self._runs_by_id[run_id]
        order = {Outcome.ERROR: 0, Outcome.FAILED: 1, Outcome.SKIPPED: 2, Outcome.PASSED: 3}
        results = sorted(run.results, key=lambda r: (order[r.outcome], r.key))
        return RunDetail(run=_run_view(run), executions=tuple(_execution_view(run, r) for r in results))

    def stability(
        self, scope: Scope = EVERYTHING, settings: HistorySettings = DEFAULTS, include_stable: bool = False
    ) -> StabilityView:
        """History classification of every test in the chosen runs (docs/metrics.md, history)."""
        runs = self._runs(scope)
        cases = self._case_ids_by_key(runs)
        classified = stability_report(runs, settings)
        counts: dict[str, int] = {}
        for row in classified:
            counts[row.status.value] = counts.get(row.status.value, 0) + 1
        shown = [r for r in classified if include_stable or r.status is not Stability.STABLE]
        return StabilityView(
            status_counts=counts,
            rows=tuple(
                StabilityRow(
                    key=r.key,
                    context=_context_label(r.context),
                    status=r.status.value,
                    verdicts=r.verdicts,
                    failures=r.failures,
                    failure_rate=RatioView.of(r.failure_rate),
                    reasons=r.reasons,
                    last_outcome=r.last_outcome,
                    last_failure=r.last_failure,
                    test_cases=cases.get(r.key, ()),
                )
                for r in shown
            ),
            recurring_failures=tuple(
                RecurringView(signature=f.signature, occurrences=f.occurrences, runs=f.runs, tests=f.tests)
                for f in recurring_failures(runs)
            ),
            duration_regressions=tuple(
                RegressionView(
                    key=r.key,
                    context=_context_label(r.context),
                    baseline_seconds=r.baseline_seconds,
                    latest_seconds=r.latest_seconds,
                    baseline_runs=r.baseline_runs,
                )
                for r in duration_regressions(runs, settings)
            ),
            trends={
                _context_label(context): tuple(
                    TrendPoint(
                        run_id=p.run.run_id,
                        source=p.run.source,
                        started_at=p.run.started_at,
                        build=p.run.context.build,
                        pass_rate=RatioView.of(p.pass_rate),
                        failed=p.failed,
                    )
                    for p in points
                )
                for context, points in trend(runs).items()
            },
            window=settings.window,
        )

    # ---- helpers -------------------------------------------------------------------------

    def _runs(self, scope: Scope) -> tuple[TestRun, ...]:
        """Runs kept by the run filters, oldest first."""
        return tuple(run for run in self.runs if scope.run_filters.keeps(run))

    def _report(self, scope: Scope) -> TraceabilityReport:
        """Traceability report for the scope."""
        return build_report(self.catalog, self.runs, scope.filters, scope.run_filters)

    def _case_ids_by_key(self, runs: Iterable[TestRun]) -> dict[str, tuple[str, ...]]:
        """Test case ids each result key belongs to."""
        matching = match_results(self.catalog, runs)
        found: dict[str, set[str]] = {}
        for case_id, executions in matching.by_case.items():
            for execution in executions:
                found.setdefault(execution.result.key, set()).add(case_id)
        return {key: tuple(sorted(ids)) for key, ids in found.items()}

    def _row(self, requirement: Requirement, report: TraceabilityReport) -> RequirementRow:
        """List row for one requirement, counting only the test cases that are in the scope."""
        in_scope = next(
            (row for row in report.coverage.requirements if row.requirement.id == requirement.id), None
        )
        cases = in_scope.test_cases if in_scope else self.catalog.test_cases_for(requirement.id)
        automated = sum(1 for c in cases if c.automation_status is AutomationStatus.AUTOMATED)
        coverage_status = "no tests" if not cases else "automated" if automated else "not automated"
        return RequirementRow(
            id=requirement.id,
            title=requirement.title,
            feature=requirement.feature or UNSPECIFIED,
            criticality=_text(requirement.criticality),
            priority=_text(requirement.priority),
            risk=_text(requirement.risk),
            platforms=requirement.platforms,
            test_cases=len(cases),
            automated_test_cases=automated,
            coverage_status=coverage_status,
            execution_status=report.requirement_status.get(requirement.id, "not automated"),
        )


def _run_view(run: TestRun) -> RunView:
    """Run summary."""
    counts = run.outcome_counts()
    return RunView(
        run_id=run.run_id,
        source=run.source,
        context=run.context,
        started_at=run.started_at,
        counts=counts,
        pass_rate=RatioView.of(execution_pass_rate(counts)),
    )


def _execution_view(run: TestRun, result: TestResult) -> ExecutionView:
    """One execution with its run."""
    failure = result.failure
    return ExecutionView(
        key=result.key,
        name=result.name,
        outcome=result.outcome,
        duration_seconds=result.duration_seconds,
        retries=result.retries,
        failure=FailureView(message=failure.message, type=failure.type, text=failure.text)
        if failure
        else None,
        run_id=run.run_id,
        source=run.source,
        started_at=run.started_at,
        context=run.context,
    )


def _context_label(context: tuple[str | None, ...]) -> str:
    """Framework / environment / browser / platform, '-' for missing parts."""
    return " / ".join(part or "-" for part in context)


def _sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    """Distinct non-empty values, sorted."""
    return tuple(sorted({v for v in values if v}))


def _text(member: object) -> str:
    """Enum value, or ``unspecified``."""
    return UNSPECIFIED if member is None else str(getattr(member, "value", member))
