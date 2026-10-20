"""Read-only queries over one catalog and a set of runs, shaped for the dashboard and its API.

This module holds the logic behind every dashboard view (what is counted, in which order,
what "latest" means), so it is tested without a server or a browser. The dashboard package
only turns these view models into JSON and HTML.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from qualityintel.gates.config import GateConfig
from qualityintel.history.analysis import (
    DEFAULTS,
    HistorySettings,
    Stability,
    duration_regressions,
    recurring_failures,
    stability_report,
    trend,
)
from qualityintel.history.trends import CoverageSnapshot, coverage_changes, daily_trend
from qualityintel.ingest.batch import Batch, import_results
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.models.catalog import Catalog, Requirement
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.enums import AutomationStatus, Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import PipelineJob, RunContext, TestResult, TestRun
from qualityintel.readiness import readiness
from qualityintel.traceability.coverage import UNSPECIFIED, Filters
from qualityintel.traceability.matching import match_results
from qualityintel.traceability.pipelines import PipelineExecution, pipeline_execution, pipeline_ids
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
    pipeline: PipelineJob | None = None


class PipelineJobView(View):
    """One job of a pipeline execution: its highest attempt."""

    name: str
    attempt: int
    expected: bool
    run_ids: tuple[str, ...]
    superseded_runs: int
    counts: dict[Outcome, int]
    pass_rate: RatioView
    started_at: datetime | None = None


class AttemptView(View):
    """One collected attempt of a pipeline run (a re-run is attempt 2)."""

    attempt: int
    conclusion: str
    state: str
    collected_at: datetime
    runs: int
    results: int
    problems: tuple[str, ...]


class PipelineView(View):
    """One pipeline execution (docs/pipelines.md), with what collection recorded about it.

    Attributes:
        status: ``incomplete`` when jobs or reports are missing (whatever the CI concluded),
            else the CI conclusion of the latest attempt (``success``, ``failure``,
            ``cancelled`` ...), else ``complete`` for pipelines imported without collection.
    """

    pipeline_id: str
    state: str
    status: str
    conclusion: str | None
    repository: str | None
    workflow: str | None
    run_number: int | None
    url: str | None
    commit_url: str | None
    branch: str | None
    commit: str | None
    started_at: datetime | None
    jobs: tuple[PipelineJobView, ...]
    missing: tuple[str, ...]
    problems: tuple[str, ...]
    counts: dict[Outcome, int]
    pass_rate: RatioView
    attempts: tuple[AttemptView, ...] = ()


class PipelinesView(View):
    """Every pipeline execution in scope, newest first, judged against the expected jobs.

    Attributes:
        status_counts: Pipelines per status before the status filter (for the filter chips).
        workflows: Workflows present (for the workflow filter).
    """

    expected_jobs: tuple[str, ...]
    pipelines: tuple[PipelineView, ...]
    notes: tuple[str, ...]
    status_counts: dict[str, int] = {}
    workflows: tuple[str, ...] = ()


class RepositoryHealth(View):
    """Collection of one repository over the last 7 days."""

    repository: str
    workflows: tuple[str, ...]
    last_collected_at: datetime | None
    latest_run_started_at: datetime | None
    fresh: bool
    freshness: str
    pipelines: int
    complete: int
    incomplete: int
    results: int
    conclusions: dict[str, int]
    problems: tuple[str, ...]


class CollectionHealthView(View):
    """Health of CI collection per repository (docs/collection.md)."""

    expected_hours: float
    workflow_url: str | None
    repositories: tuple[RepositoryHealth, ...]
    notes: tuple[str, ...]


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
    description: str | None
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


class GateRuleView(View):
    """One rule of the release gate as it applies to the chosen scope."""

    name: str
    status: str
    fails_gate: bool
    actual: str
    expected: str
    explanation: str


class ReadinessView(View):
    """The overview's release status and its headline numbers (docs/readiness.md)."""

    state: str
    reasons: tuple[str, ...]
    gate_name: str | None
    rules: tuple[GateRuleView, ...]
    executions: int
    pass_rate: RatioView
    requirement_coverage: RatioView
    automated_requirement_coverage: RatioView
    critical_without_automation: int
    flaky_candidates: int
    incomplete_pipelines: int
    latest_collection_at: datetime | None


class StabilityView(View):
    """Everything the history analysis says about the chosen runs."""

    status_counts: dict[str, int]
    rows: tuple[StabilityRow, ...]
    recurring_failures: tuple[RecurringView, ...]
    duration_regressions: tuple[RegressionView, ...]
    trends: dict[str, tuple[TrendPoint, ...]]
    window: int


class DailyView(View):
    """One day in the execution trend (the snapshot at the end of that day)."""

    day: date
    counts: dict[Outcome, int]
    pass_rate: RatioView
    duration_seconds: float
    requirement_status: dict[str, int]
    contexts: int
    carried: tuple[str, ...]
    added: tuple[str, ...]


class RunTrendView(View):
    """One run in its context's series."""

    run_id: str
    source: str
    started_at: datetime | None
    build: str | None
    counts: dict[Outcome, int]
    pass_rate: RatioView
    duration_seconds: float


class CoverageView(View):
    """A recorded coverage snapshot of the catalog."""

    taken_at: datetime
    catalog: str
    requirements: int
    requirement_coverage: RatioView
    automation_coverage: RatioView
    automated_requirement_coverage: RatioView


class TrendsView(View):
    """Everything the trends page draws, with notes about what it cannot show."""

    daily: tuple[DailyView, ...]
    runs: dict[str, tuple[RunTrendView, ...]]
    coverage: tuple[CoverageView, ...]
    notes: tuple[str, ...]


class Facets(View):
    """Filter values that exist in the data, for the dashboard's drop-downs."""

    features: tuple[str, ...]
    criticalities: tuple[str, ...]
    platforms: tuple[str, ...]
    test_types: tuple[str, ...]
    frameworks: tuple[str, ...]
    environments: tuple[str, ...]
    browsers: tuple[str, ...]
    builds: tuple[str, ...]
    repositories: tuple[str, ...] = ()


@dataclass(frozen=True)
class Scope:
    """Every filter the dashboard offers, in one object."""

    filters: Filters = field(default_factory=Filters)
    run_filters: RunFilters = field(default_factory=RunFilters)


# The default for every query: no filter at all (Scope is immutable, so one instance is safe)
EVERYTHING = Scope()


class Workspace:
    """A catalog and the runs imported for it."""

    def __init__(
        self,
        catalog: Catalog,
        runs: Iterable[TestRun],
        snapshots: Sequence[CoverageSnapshot] = (),
        collections: Sequence[PipelineCollection] = (),
        gate: GateConfig | None = None,
    ) -> None:
        self.catalog = catalog
        self.snapshots = tuple(snapshots)
        self.collections = tuple(collections)
        self.gate = gate
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
            builds=_sorted(r.context.build for r in self.runs if r.context.build),
            repositories=_sorted(
                r.pipeline.repository for r in self.runs if r.pipeline and r.pipeline.repository
            ),
        )

    def readiness(
        self, scope: Scope = EVERYTHING, stale: bool = False, now: datetime | None = None
    ) -> ReadinessView:
        """Release status of the scope by the documented policy, with the numbers behind it."""
        report = self._report(scope)
        flaky = self.stability(scope).status_counts.get("flaky candidate", 0)
        week_ago = (now or datetime.now(UTC)) - timedelta(days=7)
        chosen = scope.run_filters.repositories
        recent = [
            c
            for c in self.collections
            if c.collected_at >= week_ago and (not chosen or c.repository in chosen)
        ]
        incomplete = sum(c.state == "incomplete" for c in recent)
        decision = readiness(report, self.gate, flaky, incomplete, stale)
        totals = report.coverage.totals
        rules = decision.gate.rules if decision.gate else []
        return ReadinessView(
            state=decision.state.value,
            reasons=decision.reasons,
            gate_name=self.gate.name if self.gate else None,
            rules=tuple(
                GateRuleView(
                    name=rule.name,
                    status=rule.status.value,
                    fails_gate=rule.counts_as_failure,
                    actual=rule.actual,
                    expected=rule.expected,
                    explanation=rule.explanation,
                )
                for rule in rules
            ),
            executions=sum(report.outcome_counts.values()),
            pass_rate=RatioView.of(report.pass_rate),
            requirement_coverage=RatioView.of(totals.requirement_coverage),
            automated_requirement_coverage=RatioView.of(totals.automated_requirement_coverage),
            critical_without_automation=len(report.coverage.uncovered_critical),
            flaky_candidates=flaky,
            incomplete_pipelines=incomplete,
            latest_collection_at=max((c.collected_at for c in self.collections), default=None),
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

    def pipelines(
        self,
        scope: Scope = EVERYTHING,
        expected_jobs: Sequence[str] = (),
        status: str | None = None,
        workflow: str | None = None,
    ) -> PipelinesView:
        """Pipeline executions in scope, each assembled from all its runs, with their collection records.

        A filter such as ``browser`` chooses which executions are listed, but never removes jobs
        from an execution: a pipeline filtered to its Chrome job would look incomplete. Collected
        pipelines without any run (cancelled before uploading) are listed too, as long as no
        run-context filter is chosen (nothing about their context is known).
        """
        expected = tuple(dict.fromkeys(job for job in expected_jobs if job))
        filters = scope.run_filters
        ids = pipeline_ids(self._runs(scope))
        context_chosen = any(
            (filters.frameworks, filters.environments, filters.browsers, filters.platforms, filters.builds)
        )
        if not context_chosen:
            for record in self.collections:
                if _record_in_scope(record, filters) and record.pipeline_id not in ids:
                    ids.append(record.pipeline_id)
        views = [
            _pipeline_view(
                pipeline_execution(self.runs, pid, expected),
                [c for c in self.collections if c.pipeline_id == pid],
            )
            for pid in ids
        ]
        workflows = tuple(sorted({v.workflow for v in views if v.workflow}))
        if workflow:
            views = [v for v in views if v.workflow == workflow]
        counts: dict[str, int] = {}
        for view in views:
            counts[view.status] = counts.get(view.status, 0) + 1
        if status:
            views = [v for v in views if v.status == status]
        views.sort(key=lambda v: (v.started_at is None, v.started_at))
        notes = []
        if not expected:
            notes.append(
                "No expected jobs given: an execution counts as incomplete only when its jobs disagree on "
                "branch or commit or report no results. Name the jobs the pipeline must have to find "
                "executions with missing jobs."
            )
        return PipelinesView(
            expected_jobs=expected,
            pipelines=tuple(reversed(views)),
            notes=tuple(notes),
            status_counts=counts,
            workflows=workflows,
        )

    def collection_health(
        self, now: datetime | None = None, expected_hours: float = 26.0, workflow_url: str | None = None
    ) -> CollectionHealthView:
        """Per repository: last collection, freshness against the expected schedule, last 7 days' records."""
        now = now or datetime.now(UTC)
        week_ago = now - timedelta(days=7)
        rows = []
        for repository in sorted({c.repository for c in self.collections}):
            records = [c for c in self.collections if c.repository == repository]
            recent = [c for c in records if c.collected_at >= week_ago]
            last = max(c.collected_at for c in records)
            age_hours = (now - last).total_seconds() / 3600
            fresh = age_hours <= expected_hours
            conclusions: dict[str, int] = {}
            for record in recent:
                conclusions[record.conclusion] = conclusions.get(record.conclusion, 0) + 1
            starts = [c.started_at for c in records if c.started_at is not None]
            rows.append(
                RepositoryHealth(
                    repository=repository,
                    workflows=tuple(sorted({c.workflow for c in records})),
                    last_collected_at=last,
                    latest_run_started_at=max(starts, default=None),
                    fresh=fresh,
                    freshness=f"collected {age_hours:.0f} h ago"
                    + ("" if fresh else f", more than the expected {expected_hours:.0f} h"),
                    pipelines=len(recent),
                    complete=sum(c.state == "complete" for c in recent),
                    incomplete=sum(c.state == "incomplete" for c in recent),
                    results=sum(c.results for c in recent),
                    conclusions=dict(sorted(conclusions.items())),
                    problems=tuple(
                        f"{c.pipeline_id} attempt {c.attempt}: {p}" for c in recent for p in c.problems
                    ),
                )
            )
        notes = []
        if not rows:
            notes.append(
                "No collection recorded: this dashboard reads files or imports, not collected CI history."
            )
        notes.append(
            "Restoring the history between collection runs is reported in the collection workflow's log, "
            "not in the database."
        )
        return CollectionHealthView(
            expected_hours=expected_hours,
            workflow_url=workflow_url,
            repositories=tuple(rows),
            notes=tuple(notes),
        )

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

    def trends(self, scope: Scope = EVERYTHING) -> TrendsView:
        """Daily snapshots, per-context run series and recorded coverage (docs/metrics.md, trends)."""
        runs = self._runs(scope)
        daily = daily_trend(runs, self.catalog, scope.filters)
        notes = list(coverage_changes(self.snapshots))
        undated = sum(1 for r in runs if r.started_at is None)
        if undated:
            notes.append(f"{undated} run(s) without a start time are not on the time axis")
        carried_days = [p.day.isoformat() for p in daily if p.carried]
        if carried_days:
            notes.append(
                f"{len(carried_days)} day(s) combine a run of that day with older latest runs of other "
                "contexts (listed per day): those points are not one test run"
            )
        changes = [p.day.isoformat() for p in daily if p.added]
        if changes:
            notes.append(
                f"the set of run contexts grows on {', '.join(changes)}: totals before and after "
                "those days count different suites; compare pass rates, or filter to one framework"
            )
        if not runs:
            notes.append("no runs in this scope")
        return TrendsView(
            daily=tuple(
                DailyView(
                    day=p.day,
                    counts=p.counts,
                    pass_rate=RatioView.of(p.pass_rate),
                    duration_seconds=round(p.duration_seconds, 3),
                    requirement_status=p.requirement_status,
                    contexts=p.contexts,
                    carried=p.carried,
                    added=p.added,
                )
                for p in daily
            ),
            runs={
                _context_label(context): tuple(
                    RunTrendView(
                        run_id=p.run.run_id,
                        source=p.run.source,
                        started_at=p.run.started_at,
                        build=p.run.context.build,
                        counts=p.run.outcome_counts(),
                        pass_rate=RatioView.of(p.pass_rate),
                        duration_seconds=round(p.total_seconds, 3),
                    )
                    for p in points
                )
                for context, points in trend(runs).items()
            },
            coverage=tuple(
                CoverageView(
                    taken_at=s.taken_at,
                    catalog=s.catalog,
                    requirements=s.requirements,
                    requirement_coverage=RatioView.of(s.requirement_coverage),
                    automation_coverage=RatioView.of(s.automation_coverage),
                    automated_requirement_coverage=RatioView.of(s.automated_requirement_coverage),
                )
                for s in self.snapshots
            ),
            notes=tuple(notes),
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
            description=requirement.description,
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
        pipeline=run.pipeline,
    )


def _record_in_scope(record: PipelineCollection, filters: RunFilters) -> bool:
    """A collection record matches the repository and date filters (its context is unknown)."""
    if filters.repositories and record.repository not in filters.repositories:
        return False
    if filters.since is not None or filters.until is not None:
        if record.started_at is None:
            return False
        day = record.started_at.astimezone(UTC).date()
        if (filters.since and day < filters.since) or (filters.until and day > filters.until):
            return False
    return True


def _pipeline_view(execution: PipelineExecution, records: Sequence[PipelineCollection] = ()) -> PipelineView:
    """Pipeline execution summary with per-job counts and its collection records."""
    counts = dict.fromkeys(Outcome, 0)
    jobs = []
    for job in execution.jobs:
        job_counts = job.outcome_counts
        for outcome, n in job_counts.items():
            counts[outcome] += n
        jobs.append(
            PipelineJobView(
                name=job.name,
                attempt=job.attempt,
                expected=job.expected,
                run_ids=tuple(run.run_id for run in job.runs),
                superseded_runs=len(job.superseded),
                counts=job_counts,
                pass_rate=RatioView.of(execution_pass_rate(job_counts)),
                started_at=min((r.started_at for r in job.runs if r.started_at), default=None),
            )
        )
    starts = [run.started_at for run in execution.runs if run.started_at is not None]
    ordered = sorted(records, key=lambda c: c.attempt)
    latest = ordered[-1] if ordered else None
    repository = next(
        (r.pipeline.repository for r in execution.runs if r.pipeline and r.pipeline.repository), None
    )
    repository = repository or (latest.repository if latest else None)
    commit = execution.commit or (latest.commit if latest else None)
    incomplete = execution.problems != () if execution.runs else True
    if latest is not None and latest.state == "incomplete":
        incomplete = True
    status = "incomplete" if incomplete else (latest.conclusion if latest else "complete")
    recorded = list(latest.problems) if latest else []
    # "no runs were read" only repeats the recorded reasons (missing artifacts) when there are any
    derived = [
        p for p in execution.problems if not (recorded and p.endswith("no runs of this pipeline were read"))
    ]
    problems = tuple(dict.fromkeys([*recorded, *derived]))
    return PipelineView(
        pipeline_id=execution.pipeline_id,
        state=execution.state.value if execution.runs else "incomplete",
        status=status,
        conclusion=latest.conclusion if latest else None,
        repository=repository,
        workflow=latest.workflow if latest else None,
        run_number=latest.run_number if latest else None,
        url=latest.url if latest and latest.url.startswith("https://github.com/") else None,
        commit_url=f"https://github.com/{repository}/commit/{commit}" if repository and commit else None,
        branch=execution.branch or (latest.branch if latest else None),
        commit=commit,
        started_at=min(starts) if starts else (latest.started_at if latest else None),
        jobs=tuple(jobs),
        missing=execution.missing,
        problems=problems,
        counts=counts,
        pass_rate=RatioView.of(execution_pass_rate(counts)),
        attempts=tuple(
            AttemptView(
                attempt=c.attempt,
                conclusion=c.conclusion,
                state=c.state,
                collected_at=c.collected_at,
                runs=c.runs,
                results=c.results,
                problems=c.problems,
            )
            for c in ordered
        ),
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
