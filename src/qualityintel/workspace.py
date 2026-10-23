"""Read-only queries over one catalog and a set of runs, shaped for the dashboard and its API.

This module holds the logic behind every dashboard view (what is counted, in which order,
what "latest" means), so it is tested without a server or a browser. The dashboard package
only turns these view models into JSON and HTML.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TypeVar, cast

from pydantic import BaseModel, ConfigDict

from qualityintel.attention import (
    OPEN,
    RESOLVED,
    SEVERITY,
    SUSPECTED,
    UNKNOWN,
    latest_outcomes,
    newly_failing,
    pipeline_states,
    recurring_state,
)
from qualityintel.gates.config import GateConfig
from qualityintel.history.analysis import (
    DEFAULTS,
    HistorySettings,
    Stability,
    duration_regressions,
    recurring_failures,
    stability_report,
    timelines,
    trend,
)
from qualityintel.history.analysis import Execution as HistoryExecution
from qualityintel.history.builds import BuildSide, builds_in_order, compare_builds, label
from qualityintel.history.trends import CoverageSnapshot, coverage_changes, daily_trend
from qualityintel.ingest.batch import Batch, import_results
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.links import github_run_url
from qualityintel.models.catalog import Catalog, Requirement
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.enums import AutomationStatus, Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import PipelineJob, RunContext, TestResult, TestRun
from qualityintel.readiness import readiness
from qualityintel.search import build_index, search
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


class CollectionIssue(View):
    """One problem of one collected pipeline attempt, with where to look."""

    pipeline_id: str
    attempt: int
    run_url: str | None
    text: str


class RepositoryHealth(View):
    """Collection of one repository over the last 7 days."""

    repository: str
    workflows: tuple[str, ...]
    last_collected_at: datetime | None
    latest_run_started_at: datetime | None
    last_complete_collection_at: datetime | None = None
    fresh: bool
    freshness: str
    pipelines: int
    complete: int
    incomplete: int
    results: int
    conclusions: dict[str, int]
    problems: tuple[str, ...]
    issues: tuple[CollectionIssue, ...] = ()


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
    pipeline: PipelineJob | None = None
    ci_url: str | None = None
    workflow: str | None = None


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
    owner: str = UNSPECIFIED
    coverage_status: str
    execution_status: str
    last_executed_at: datetime | None = None
    stale: bool = False
    observed: bool = False


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


class ExecutionDay(View):
    """Recorded results grouped by the imported run's UTC start date."""

    day: date
    counts: dict[Outcome, int]


class ExecutionRank(View):
    """One test within a repository, job, suite and execution context."""

    key: str
    name: str
    suite: str
    repository: str | None
    job: str | None
    context: RunContext
    executions: int
    failed: int
    errors: int
    timed_executions: int
    average_seconds: float | None
    max_seconds: float | None


class ExecutionOption(View):
    """One recorded context for the guided repository/type/browser picker."""

    repository: str
    kind: str
    job: str
    browser: str
    framework: str
    executions: int


def execution_kind(run: TestRun) -> str:
    """Navigation labels from explicit job conventions; ambiguous jobs remain Other.

    These are execution families, not requirement/catalog coverage classifications.
    A browser on its own is not sufficient evidence of a UI job (API tests use browsers too).
    """
    job = run.pipeline.job.lower().replace("_", "-") if run.pipeline else ""
    if run.context.framework == "k6":
        return "performance"
    if job == "api" or job.startswith(("api-", "checks-api")):
        return "api"
    if job == "unit" or job.startswith(("unit-", "checks-service-unit")):
        return "unit"
    if job.startswith("component"):
        return "component"
    if job.startswith("visual"):
        return "visual"
    if job.startswith(("a11y", "accessibility")):
        return "accessibility"
    if job in {"android", "ios", "emulation"} or job.startswith("mobile"):
        return "mobile"
    if job in {"consumer", "provider"} or job.startswith("contract"):
        return "contract"
    if job.startswith("integration"):
        return "integration"
    if job in {"chromium", "firefox", "webkit"} or job.startswith(("ui-", "e2e-")) or job == "ui":
        return "ui"
    if run.context.browser and job.startswith(("smoke", "regression", "full", "grid")):
        return "ui"
    return "other"


class ExecutionDashboard(View):
    """Historical execution counts; deliberately separate from snapshot coverage."""

    executions: int
    unique_tests: int
    suites: tuple[str, ...]
    runs: int
    counts: dict[Outcome, int]
    percentages: dict[Outcome, float | None]
    recorded_duration_seconds: float | None
    timed_executions: int
    undated_executions: int
    daily: tuple[ExecutionDay, ...]
    slowest: tuple[ExecutionRank, ...]
    failures: tuple[ExecutionRank, ...]
    errors: tuple[ExecutionRank, ...]


class TestHistory(View):
    """Every execution of one test, newest first."""

    __test__ = False  # not a pytest test class, despite the name

    key: str
    test_cases: tuple[str, ...]
    executions: tuple[ExecutionView, ...]
    requirements: tuple[str, ...] = ()
    passed: int = 0
    failed: int = 0
    # One line per context: its stability class and the reasons (docs/metrics.md, history)
    stability: tuple[str, ...] = ()


class BuildSideView(View):
    """One build in a comparison."""

    build: str
    runs: int
    counts: dict[Outcome, int]
    pass_rate: RatioView
    last_started_at: datetime | None
    requirement_coverage: RatioView | None
    automated_requirement_coverage: RatioView | None
    # GitHub runs of the pipelines whose results make up the build, and those collected incomplete
    ci_runs: tuple[str, ...] = ()
    incomplete_pipelines: tuple[str, ...] = ()


class ChangeRow(View):
    """One test that changed between two builds, in one comparable suite."""

    category: str
    key: str
    context: str
    base_outcome: Outcome | None
    head_outcome: Outcome | None
    base_seconds: float | None
    head_seconds: float | None


class BuildComparisonView(View):
    """Two builds side by side (docs/history.md, "Comparing builds")."""

    base: BuildSideView
    head: BuildSideView
    comparable: bool
    compared_contexts: tuple[str, ...]
    only_in_base: tuple[str, ...]
    only_in_head: tuple[str, ...]
    changes: tuple[ChangeRow, ...]
    category_counts: dict[str, int]
    notes: tuple[str, ...]


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
    affected_builds: tuple[str, ...] = ()
    last_failed_at: datetime | None = None
    last_failing_run_id: str | None = None
    last_passing_run_id: str | None = None


class MatrixRow(View):
    """Requirements of one criticality (or feature) by coverage and execution status."""

    group: str
    total: int
    coverage: dict[str, int]
    execution: dict[str, int]
    stale: int


class RepositoryMatrixRow(View):
    """Requirement execution evidence observed in one repository."""

    repository: str
    observed_requirements: int
    execution: dict[str, int]
    stale: int


class RequirementMatrix(View):
    """Requirements by criticality, feature, owner and observed repository evidence."""

    by_criticality: tuple[MatrixRow, ...]
    by_feature: tuple[MatrixRow, ...]
    by_owner: tuple[MatrixRow, ...] = ()
    by_repository: tuple[RepositoryMatrixRow, ...] = ()
    stale_days: int


class RecurringView(View):
    """A failure signature seen in several runs, in rank order (docs/metrics.md).

    ``run_ids`` are the newest supporting runs (at most ``RECURRING_RUNS_LISTED``); ``runs``
    counts all of them.
    """

    signature: str
    occurrences: int
    runs: int
    tests: tuple[str, ...]
    recent_runs: int
    first_seen: datetime | None
    last_seen: datetime | None
    run_ids: tuple[str, ...]


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
    owners: tuple[str, ...] = ()
    frameworks: tuple[str, ...]
    environments: tuple[str, ...]
    browsers: tuple[str, ...]
    builds: tuple[str, ...]
    repositories: tuple[str, ...] = ()
    jobs: tuple[str, ...] = ()


class SearchHit(View):
    """One search result and where it leads (docs/dashboard.md, Search)."""

    kind: str
    identifier: str
    title: str
    route: str
    params: dict[str, str]
    repositories: tuple[str, ...]
    first_seen: datetime | None
    last_seen: datetime | None
    url: str | None


class SearchView(View):
    """Search results grouped by kind, at most ``limit`` per group, with full counts."""

    query: str
    total: int
    counts: dict[str, int]
    groups: dict[str, tuple[SearchHit, ...]]
    limit: int


class FindingView(View):
    """One *Needs attention* finding with the evidence behind it (docs/attention.md)."""

    kind: str
    severity: int
    state: str
    title: str
    why: str
    evidence: int
    evidence_label: str
    first_seen: datetime | None
    last_seen: datetime | None
    repository: str | None
    route: str
    params: dict[str, str]
    url: str | None


class AttentionView(View):
    """Findings, open ones first, then by documented severity and recency."""

    findings: tuple[FindingView, ...]
    counts: dict[str, int]
    states: dict[str, int]
    shown: int
    total: int
    notes: tuple[str, ...]


@dataclass(frozen=True)
class Scope:
    """Every filter the dashboard offers, in one object."""

    filters: Filters = field(default_factory=Filters)
    run_filters: RunFilters = field(default_factory=RunFilters)


# The default for every query: no filter at all (Scope is immutable, so one instance is safe)
EVERYTHING = Scope()


# Distinct filter combinations whose analyses one workspace keeps (each holds a few MB at most)
MAX_CACHED_VIEWS = 64
# Newest supporting runs a recurring failure links to (its run count covers all of them)
RECURRING_RUNS_LISTED = 10
T = TypeVar("T")


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
        # Evidence older than this is stale (docs/dashboard.md); a deployment can change it
        self.stale_days = 14
        self.runs = tuple(sorted(runs, key=lambda r: (r.started_at is None, r.started_at, r.source)))
        self._runs_by_id = {run.run_id: run for run in self.runs}
        # Results of time-independent analyses: a workspace never changes, so they hold until
        # the data is reloaded (a new workspace). Bounded: the oldest entry goes first.
        self._cache: dict[Hashable, object] = {}

    def _cached(self, key: Hashable, compute: Callable[[], T]) -> T:
        """``compute()`` once per key for this workspace (at most MAX_CACHED_VIEWS kept)."""
        if key in self._cache:
            return cast(T, self._cache[key])
        value = compute()
        if len(self._cache) >= MAX_CACHED_VIEWS:
            del self._cache[next(iter(self._cache))]
        self._cache[key] = value
        return value

    def warm(self) -> None:
        """Compute the views every visitor starts with, before this workspace goes live."""
        self.summary()
        self.stability()
        self.tests()
        self.trends()
        self.attention()
        self._cached(("search-index",), lambda: build_index(self.catalog, self.runs, self.collections))

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
            owners=_sorted(r.owner or UNSPECIFIED for r in reqs),
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
            jobs=_sorted(r.pipeline.job for r in self.runs if r.pipeline),
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
        self,
        scope: Scope = EVERYTHING,
        status: str | None = None,
        observed: bool | None = None,
        stale: bool | None = None,
        coverage_status: str | None = None,
        execution_status: str | None = None,
    ) -> tuple[RequirementRow, ...]:
        """In-scope requirements, optionally filtered by status, observed results, or stale evidence."""
        report = self._report(scope)
        rows = tuple(self._row(row.requirement, report) for row in report.coverage.requirements)
        if status:
            rows = tuple(r for r in rows if status in (r.coverage_status, r.execution_status))
        if coverage_status:
            rows = tuple(r for r in rows if r.coverage_status == coverage_status)
        if execution_status:
            rows = tuple(r for r in rows if r.execution_status == execution_status)
        if observed is not None:
            rows = tuple(r for r in rows if r.observed is observed)
        if stale is not None:
            rows = tuple(r for r in rows if r.stale is stale)
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
        """Cached per snapshot: see :meth:`_compute_tests`."""
        return self._cached(
            ("tests", scope, outcome), lambda: self._compute_tests(scope=scope, outcome=outcome)
        )

    def _compute_tests(
        self, scope: Scope = EVERYTHING, outcome: Outcome | None = None
    ) -> tuple[TestRow, ...]:
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

    def execution_dashboard(
        self,
        scope: Scope = EVERYTHING,
        limit: int = 10,
        suite: str | None = None,
        kind: str | None = None,
    ) -> ExecutionDashboard:
        """All recorded executions in scope, grouped without merging unrelated contexts.

        Counts include every imported report, not just the latest snapshot. A missing
        duration stays unknown; zero is a valid duration. Dates use run start times in
        UTC. Rankings keep repository/job/suite/framework/environment/browser/platform
        separate and omit build so repeat executions can be compared across builds.
        """
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        return self._cached(
            ("execution-dashboard", scope, limit, suite, kind),
            lambda: self._execution_dashboard(scope, limit, suite, kind),
        )

    def execution_options(self) -> tuple[ExecutionOption, ...]:
        """Only combinations that actually have imported executions; no fabricated facets."""

        def compute() -> tuple[ExecutionOption, ...]:
            counts: Counter[tuple[str, ...]] = Counter()
            for run in self.runs:
                key = (
                    run.pipeline.repository or "" if run.pipeline else "",
                    execution_kind(run),
                    run.pipeline.job if run.pipeline else "",
                    run.context.browser or "",
                    run.context.framework or "",
                )
                counts[key] += len(run.results)
            return tuple(
                ExecutionOption(
                    repository=k[0], kind=k[1], job=k[2], browser=k[3], framework=k[4], executions=n
                )
                for k, n in sorted(counts.items())
                if n
            )

        return self._cached(("execution-options",), compute)

    def _execution_dashboard(
        self, scope: Scope, limit: int, suite: str | None, kind: str | None
    ) -> ExecutionDashboard:
        runs = [r for r in self._runs(scope) if kind is None or execution_kind(r) == kind]
        suites = tuple(sorted({result.suite for run in runs for result in run.results}))
        matched_runs: set[str] = set()
        counts: Counter[Outcome] = Counter()
        days: dict[date, Counter[Outcome]] = defaultdict(Counter)
        groups: dict[tuple[str, ...], list[TestResult]] = defaultdict(list)
        contexts: dict[tuple[str, ...], tuple[RunContext, str | None, str | None]] = {}
        undated = 0
        durations: list[float] = []
        for run in runs:
            repository = run.pipeline.repository if run.pipeline else None
            job = run.pipeline.job if run.pipeline else None
            context = run.context.model_copy(update={"build": None})
            for result in run.results:
                if suite is not None and result.suite != suite:
                    continue
                matched_runs.add(run.run_id)
                counts[result.outcome] += 1
                if run.started_at is None:
                    undated += 1
                else:
                    days[run.started_at.astimezone(UTC).date()][result.outcome] += 1
                if result.duration_seconds is not None:
                    durations.append(result.duration_seconds)
                key = (
                    repository or "",
                    job or "",
                    context.framework or "",
                    context.environment or "",
                    context.browser or "",
                    context.platform or "",
                    result.suite,
                    result.key,
                )
                groups[key].append(result)
                contexts[key] = context, repository, job
        rows = []
        for group_key, results in sorted(groups.items()):
            timed = [r.duration_seconds for r in results if r.duration_seconds is not None]
            context, repository, job = contexts[group_key]
            rows.append(
                ExecutionRank(
                    key=results[-1].key,
                    name=results[-1].name,
                    suite=results[-1].suite,
                    repository=repository,
                    job=job,
                    context=context,
                    executions=len(results),
                    failed=sum(r.outcome is Outcome.FAILED for r in results),
                    errors=sum(r.outcome is Outcome.ERROR for r in results),
                    timed_executions=len(timed),
                    average_seconds=sum(timed) / len(timed) if timed else None,
                    max_seconds=max(timed) if timed else None,
                )
            )
        # Sorted group keys make equal-count rankings reproducible.
        total = sum(counts.values())
        return ExecutionDashboard(
            executions=total,
            unique_tests=len({(key[0], key[-1]) for key in groups}),
            suites=suites,
            runs=len(matched_runs),
            counts={o: counts[o] for o in Outcome},
            percentages={o: 100 * counts[o] / total if total else None for o in Outcome},
            recorded_duration_seconds=sum(durations) if durations else None,
            timed_executions=len(durations),
            undated_executions=undated,
            daily=tuple(
                ExecutionDay(day=day, counts={o: values[o] for o in Outcome})
                for day, values in sorted(days.items())
            ),
            slowest=tuple(
                sorted(
                    (r for r in rows if r.average_seconds is not None),
                    key=lambda r: -(r.average_seconds or 0),
                )[:limit]
            ),
            failures=tuple(sorted((r for r in rows if r.failed), key=lambda r: -r.failed)[:limit]),
            errors=tuple(sorted((r for r in rows if r.errors), key=lambda r: -r.errors)[:limit]),
        )

    def test_history(self, key: str, scope: Scope = EVERYTHING) -> TestHistory:
        """All executions of one test key, newest first, with its requirements (``KeyError``: never ran)."""
        runs = self._runs(scope)
        urls = {c.pipeline_id: c.url for c in self.collections if github_run_url(c.url)}
        workflows = {c.pipeline_id: c.workflow for c in self.collections}
        executions = [
            _execution_view(run, r, urls, workflows) for run in runs for r in run.results if r.key == key
        ]
        if not executions:
            raise KeyError(key)
        stability = tuple(
            f"{row.context}: {row.status}"
            + (" (suspected)" if row.status == "flaky candidate" else "")
            + (f" - {'; '.join(row.reasons)}" if row.reasons else "")
            for row in self.stability(scope, include_stable=True).rows
            if row.key == key
        )
        cases = self._case_ids_by_key(runs).get(key, ())
        requirements = sorted(
            {rid for case in self.catalog.test_cases if case.id in cases for rid in case.requirements}
        )
        return TestHistory(
            key=key,
            test_cases=cases,
            executions=tuple(reversed(executions)),
            requirements=tuple(requirements),
            passed=sum(e.outcome is Outcome.PASSED for e in executions),
            failed=sum(e.outcome in (Outcome.FAILED, Outcome.ERROR) for e in executions),
            stability=stability,
        )

    def builds(self, scope: Scope = EVERYTHING) -> tuple[str, ...]:
        """Builds in scope, in the order in which they first ran (for the comparison selectors)."""
        return tuple(builds_in_order(self._runs(_without_builds(scope))))

    def compare_builds(self, base: str, head: str, scope: Scope = EVERYTHING) -> BuildComparisonView:
        """Changes from build ``base`` to ``head`` where both ran the same suite (KeyError: unknown)."""
        runs = self._runs(_without_builds(scope))
        comparison = compare_builds(runs, base, head, self.snapshots)
        changes: list[ChangeRow] = []
        for pair in comparison.compared:
            before = {r.key: r for r in pair.base_run.results}
            after = {r.key: r for r in pair.head_run.results}
            groups = (
                ("newly failing", pair.changes.newly_failing),
                ("recovered", pair.changes.fixed),
                ("still failing", pair.changes.still_failing),
                ("new test", pair.changes.added),
                ("removed test", pair.changes.removed),
                ("slower", [key for key, _old, _new in pair.changes.slower]),
            )
            for category, keys in groups:
                for key in keys:
                    old, new = before.get(key), after.get(key)
                    changes.append(
                        ChangeRow(
                            category=category,
                            key=key,
                            context=pair.label,
                            base_outcome=old.outcome if old else None,
                            head_outcome=new.outcome if new else None,
                            base_seconds=old.duration_seconds if old else None,
                            head_seconds=new.duration_seconds if new else None,
                        )
                    )
        changes += [
            ChangeRow(
                category="newly flaky",
                key=key,
                context=context,
                base_outcome=None,
                head_outcome=None,
                base_seconds=None,
                head_seconds=None,
            )
            for key, context in comparison.newly_flaky
        ]
        counts: dict[str, int] = {}
        for change in changes:
            counts[change.category] = counts.get(change.category, 0) + 1
        notes = []
        if not comparison.comparable:
            notes.append(
                "The two builds share no suite (same context and job): nothing can be compared test by test."
            )
        if comparison.only_in_base or comparison.only_in_head:
            notes.append(
                "Suites that ran in one build only are listed, not compared: "
                "their tests are neither new nor removed."
            )
        if comparison.base.coverage is None or comparison.head.coverage is None:
            notes.append(
                "No coverage snapshot was recorded before one of the builds "
                "(qi history import --catalog records them)."
            )
        return BuildComparisonView(
            base=_side_view(comparison.base, self.collections),
            head=_side_view(comparison.head, self.collections),
            comparable=comparison.comparable,
            compared_contexts=tuple(pair.label for pair in comparison.compared),
            only_in_base=comparison.only_in_base,
            only_in_head=comparison.only_in_head,
            changes=tuple(changes),
            category_counts=counts,
            notes=tuple(notes),
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
        pipeline: str | None = None,
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
        if pipeline:
            views = [v for v in views if v.pipeline_id == pipeline]
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
            complete_records = [c for c in records if c.state == "complete"]
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
                    last_complete_collection_at=max((c.collected_at for c in complete_records), default=None),
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
                    issues=tuple(
                        CollectionIssue(
                            pipeline_id=c.pipeline_id,
                            attempt=c.attempt,
                            # the attempt's own page: GitHub keeps one per re-run
                            run_url=f"{c.url}/attempts/{c.attempt}" if github_run_url(c.url) else None,
                            text=p,
                        )
                        for c in recent
                        for p in c.problems
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
        """Cached per snapshot: see :meth:`_compute_stability`."""
        return self._cached(
            ("stability", scope, settings, include_stable),
            lambda: self._compute_stability(scope=scope, settings=settings, include_stable=include_stable),
        )

    def _compute_stability(
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
        lines = timelines(runs)
        evidence = {(r.context, r.key): _evidence(lines.get((r.context, r.key), [])) for r in shown}
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
                    last_failed_at=evidence[(r.context, r.key)][0],
                    last_failing_run_id=evidence[(r.context, r.key)][1],
                    last_passing_run_id=evidence[(r.context, r.key)][2],
                    affected_builds=r.mixed_builds,
                )
                for r in shown
            ),
            recurring_failures=tuple(
                RecurringView(
                    signature=f.signature,
                    occurrences=f.occurrences,
                    runs=f.runs,
                    tests=f.tests,
                    recent_runs=f.recent_runs,
                    first_seen=f.first_seen,
                    last_seen=f.last_seen,
                    run_ids=f.run_ids[:RECURRING_RUNS_LISTED],
                )
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
        """Cached per snapshot: see :meth:`_compute_trends`."""
        return self._cached(("trends", scope), lambda: self._compute_trends(scope=scope))

    def _compute_trends(self, scope: Scope = EVERYTHING) -> TrendsView:
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

    def search(self, query: str, scope: Scope = EVERYTHING, limit: int = 20) -> SearchView:
        """Everything whose text contains every word of ``query`` (docs/dashboard.md, Search).

        Searched: repositories, workflows, pipelines, tests, requirements and failure messages.

        Raises:
            QueryError: The query is too short or too long.
        """
        index = self._cached(
            ("search-index",), lambda: build_index(self.catalog, self.runs, self.collections)
        )
        found = search(
            index,
            query,
            scope.run_filters.repositories,
            scope.run_filters.since,
            scope.run_filters.until,
            limit,
        )
        return SearchView(
            query=found.query,
            total=found.total,
            counts=found.counts,
            groups={
                kind: tuple(
                    SearchHit(
                        kind=e.kind,
                        identifier=e.identifier,
                        title=e.title,
                        route=e.route,
                        params=dict(e.params),
                        repositories=tuple(sorted(e.repositories)),
                        first_seen=e.first_seen,
                        last_seen=e.last_seen,
                        url=github_run_url(e.url),
                    )
                    for e in entries
                )
                for kind, entries in found.groups.items()
            },
            limit=limit,
        )

    def attention(
        self,
        scope: Scope = EVERYTHING,
        now: datetime | None = None,
        limit: int = 200,
        kind: str | None = None,
    ) -> AttentionView:
        """Everything that needs attention in the scope, with its evidence (docs/attention.md)."""
        all_findings = [
            *self._cached(("attention-runs", scope), lambda: tuple(self._run_findings(scope))),
            *self._collection_findings(scope, now),
            *self._gap_findings(scope),
        ]
        order = {OPEN: 0, SUSPECTED: 1, UNKNOWN: 2, RESOLVED: 3}
        all_findings.sort(
            key=lambda f: (
                order[f.state],
                f.severity,
                -(f.last_seen.timestamp() if f.last_seen else 0.0),
                f.title,
            )
        )
        findings = [finding for finding in all_findings if kind is None or finding.kind == kind]
        counts: dict[str, int] = {}
        states: dict[str, int] = {}
        for finding in findings:
            counts[finding.kind] = counts.get(finding.kind, 0) + 1
            states[finding.state] = states.get(finding.state, 0) + 1
        notes = [
            "Open: the latest evidence still shows the problem. Resolved: later evidence shows it gone. "
            "Suspected: a flaky candidate, never a proven cause. Unknown: not enough evidence."
        ]
        if self.catalog.notice:
            notes.append(f"Coverage gaps come from the catalog: {self.catalog.notice}")
        return AttentionView(
            findings=tuple(findings[:limit]),
            counts=counts,
            states=states,
            shown=min(limit, len(findings)),
            total=len(findings),
            notes=tuple(notes),
        )

    def _run_findings(self, scope: Scope) -> list[FindingView]:
        """Findings from the runs: newly failing, recurring, slower, flaky (all time-independent)."""
        runs = self._runs(scope)
        urls = {c.pipeline_id: c.url for c in self.collections if github_run_url(c.url)}
        latest = latest_outcomes(runs)
        found: list[FindingView] = []
        for item in newly_failing(runs):
            repository = item.latest_run.pipeline.repository if item.latest_run.pipeline else None
            message = item.latest.failure.message if item.latest.failure else ""
            found.append(
                FindingView(
                    kind="newly failing",
                    severity=SEVERITY["newly failing"],
                    state=OPEN,
                    title=item.key,
                    why=(
                        f"{item.latest.outcome.value} in the latest execution of {label(item.latest_run)}"
                        f" (build {item.latest_run.context.build or '-'}), passed in the one before"
                        f" (build {item.previous_run.context.build or '-'})"
                        + (f": {message.splitlines()[0][:200]}" if message else "")
                    ),
                    evidence=2,
                    evidence_label="executions compared",
                    first_seen=item.latest_run.started_at,
                    last_seen=item.latest_run.started_at,
                    repository=repository,
                    route="/test",
                    params=_with_repository({"key": item.key}, repository),
                    url=urls.get(item.latest_run.pipeline.pipeline_id) if item.latest_run.pipeline else None,
                )
            )
        for failure in recurring_failures(runs):
            found.append(
                FindingView(
                    kind="recurring failure",
                    severity=SEVERITY["recurring failure"],
                    state=recurring_state(failure.tests, latest),
                    title=failure.signature[:200],
                    why=(
                        f"the same failure in {failure.runs} runs, {failure.recent_runs} of them in the "
                        f"7 days before the newest run ({failure.occurrences} occurrences) of "
                        f"{len(failure.tests)} test(s): {', '.join(failure.tests[:3])}"
                        + (" ..." if len(failure.tests) > 3 else "")
                    ),
                    evidence=failure.occurrences,
                    evidence_label="occurrences",
                    first_seen=failure.first_seen,
                    last_seen=failure.last_seen,
                    repository=None,
                    route="/test",
                    params={"key": failure.tests[0]},
                    url=None,
                )
            )
        for slower in duration_regressions(runs, DEFAULTS):
            found.append(
                FindingView(
                    kind="duration regression",
                    severity=SEVERITY["duration regression"],
                    state=OPEN,
                    title=slower.key,
                    why=(
                        f"{slower.latest_seconds:.1f} s in the latest runs against a median of "
                        f"{slower.baseline_seconds:.1f} s over {slower.baseline_runs} earlier runs "
                        f"({_context_label(slower.context)}), confirmed over consecutive runs"
                    ),
                    evidence=slower.baseline_runs + DEFAULTS.slow_confirm_runs,
                    evidence_label="runs",
                    first_seen=None,
                    last_seen=latest.get(slower.key, (Outcome.PASSED, None))[1],
                    repository=None,
                    route="/test",
                    params={"key": slower.key},
                    url=None,
                )
            )
        for row in self.stability(scope).rows:
            if row.status != "flaky candidate":
                continue
            found.append(
                FindingView(
                    kind="flaky candidate",
                    severity=SEVERITY["flaky candidate"],
                    state=SUSPECTED,
                    title=row.key,
                    why="; ".join(row.reasons) or "passed and failed in the same context",
                    evidence=row.verdicts,
                    evidence_label="verdicts",
                    first_seen=None,
                    last_seen=row.last_failed_at,
                    repository=None,
                    route="/test",
                    params={"key": row.key},
                    url=None,
                )
            )
        return found

    def _collection_findings(self, scope: Scope, now: datetime | None) -> list[FindingView]:
        """Incomplete pipelines (open or resolved by a later complete run) and overdue repositories."""
        records = [c for c in self.collections if _record_in_scope(c, scope.run_filters)]
        found: list[FindingView] = []
        for item in pipeline_states(records):
            record = item.record
            later = item.resolved_by
            found.append(
                FindingView(
                    kind="incomplete pipeline",
                    severity=SEVERITY["incomplete pipeline"],
                    state=item.state,
                    title=f"{record.pipeline_id} attempt {record.attempt}",
                    why=(
                        "; ".join(record.problems[:3])
                        + f" (the CI concluded {record.conclusion})"
                        + (
                            f"; later run #{later.run_number} of {later.workflow} is complete"
                            if later
                            else ""
                        )
                    ),
                    evidence=len(record.problems),
                    evidence_label="problems",
                    first_seen=record.started_at or record.collected_at,
                    last_seen=record.collected_at,
                    repository=record.repository,
                    route="/pipelines",
                    params={"repository": record.repository, "pipeline": record.pipeline_id},
                    url=f"{record.url}/attempts/{record.attempt}" if github_run_url(record.url) else None,
                )
            )
        chosen = scope.run_filters.repositories
        for row in self.collection_health(now=now).repositories:
            if row.fresh or (chosen and row.repository not in chosen):
                continue
            found.append(
                FindingView(
                    kind="overdue collection",
                    severity=SEVERITY["overdue collection"],
                    state=OPEN,
                    title=row.repository,
                    why=f"{row.freshness}: its newest results may be missing",
                    evidence=row.pipelines,
                    evidence_label="pipelines in 7 days",
                    first_seen=None,
                    last_seen=row.last_collected_at,
                    repository=row.repository,
                    route="/collection",
                    params={},
                    url=None,
                )
            )
        return found

    def _gap_findings(self, scope: Scope) -> list[FindingView]:
        """Critical requirements in scope without an automated test case."""
        rows = {r.id: r for r in self.requirements(scope)}
        return [
            FindingView(
                kind="critical gap",
                severity=SEVERITY["critical gap"],
                state=OPEN,
                title=f"{requirement.id}: {requirement.title}",
                why=(
                    "critical requirement without an automated test case"
                    + (
                        f" ({rows[requirement.id].test_cases} test case(s), none automated)"
                        if requirement.id in rows
                        else ""
                    )
                ),
                evidence=rows[requirement.id].test_cases if requirement.id in rows else 0,
                evidence_label="test cases",
                first_seen=None,
                last_seen=None,
                repository=None,
                route=f"/requirement/{requirement.id}",
                params={},
                url=None,
            )
            for requirement in self._report(scope).coverage.uncovered_critical
        ]

    def _runs(self, scope: Scope) -> tuple[TestRun, ...]:
        """Runs kept by the run filters, oldest first."""
        return tuple(run for run in self.runs if scope.run_filters.keeps(run))

    def _report(self, scope: Scope) -> TraceabilityReport:
        """Cached per snapshot: see :meth:`_compute_report`."""
        return self._cached(("report", scope), lambda: self._compute_report(scope=scope))

    def _compute_report(self, scope: Scope) -> TraceabilityReport:
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

    def requirement_matrix(self, scope: Scope = EVERYTHING, now: datetime | None = None) -> RequirementMatrix:
        """Break down catalog coverage and execution evidence by its recorded dimensions."""
        report = self._report(scope)
        rows = [self._row(row.requirement, report, now) for row in report.coverage.requirements]

        def group(attribute: str) -> tuple[MatrixRow, ...]:
            groups: dict[str, list[RequirementRow]] = {}
            for row in rows:
                groups.setdefault(getattr(row, attribute), []).append(row)
            result = []
            for name in sorted(groups):
                members = groups[name]
                coverage: dict[str, int] = {}
                execution: dict[str, int] = {}
                for member in members:
                    coverage[member.coverage_status] = coverage.get(member.coverage_status, 0) + 1
                    execution[member.execution_status] = execution.get(member.execution_status, 0) + 1
                result.append(
                    MatrixRow(
                        group=name,
                        total=len(members),
                        coverage=dict(sorted(coverage.items())),
                        execution=dict(sorted(execution.items())),
                        stale=sum(member.stale for member in members),
                    )
                )
            return tuple(result)

        repositories = {
            run.pipeline.repository for run in self.runs if run.pipeline and run.pipeline.repository
        }
        if scope.run_filters.repositories:
            repositories &= set(scope.run_filters.repositories)
        by_repository: list[RepositoryMatrixRow] = []
        for repository in sorted(repositories):
            repository_scope = replace(
                scope,
                run_filters=replace(scope.run_filters, repositories=frozenset({repository})),
            )
            repository_report = self._report(repository_scope)
            observed = [
                self._row(item.requirement, repository_report, now)
                for item in repository_report.coverage.requirements
                if any(
                    repository_report.cases[case.id].executions
                    for case in item.test_cases
                    if case.id in repository_report.cases
                )
            ]
            execution: dict[str, int] = {}
            for member in observed:
                execution[member.execution_status] = execution.get(member.execution_status, 0) + 1
            by_repository.append(
                RepositoryMatrixRow(
                    repository=repository,
                    observed_requirements=len(observed),
                    execution=dict(sorted(execution.items())),
                    stale=sum(member.stale for member in observed),
                )
            )

        return RequirementMatrix(
            by_criticality=group("criticality"),
            by_feature=group("feature"),
            by_owner=group("owner"),
            by_repository=tuple(by_repository),
            stale_days=self.stale_days,
        )

    def _row(
        self, requirement: Requirement, report: TraceabilityReport, now: datetime | None = None
    ) -> RequirementRow:
        """List row for one requirement, counting only the test cases that are in the scope."""
        in_scope = next(
            (row for row in report.coverage.requirements if row.requirement.id == requirement.id), None
        )
        cases = in_scope.test_cases if in_scope else self.catalog.test_cases_for(requirement.id)
        automated = sum(1 for c in cases if c.automation_status is AutomationStatus.AUTOMATED)
        observed = any(report.cases[c.id].executions for c in cases if c.id in report.cases)
        coverage_status = "no tests" if not cases else "automated" if automated else "not automated"
        starts = [
            e.run.started_at
            for c in cases
            if c.id in report.cases
            for e in report.cases[c.id].executions
            if e.run.started_at is not None
        ]
        last = max(starts, default=None)
        return RequirementRow(
            id=requirement.id,
            title=requirement.title,
            description=requirement.description,
            feature=requirement.feature or UNSPECIFIED,
            owner=requirement.owner or UNSPECIFIED,
            criticality=_text(requirement.criticality),
            priority=_text(requirement.priority),
            risk=_text(requirement.risk),
            platforms=requirement.platforms,
            test_cases=len(cases),
            automated_test_cases=automated,
            coverage_status=coverage_status,
            execution_status=report.requirement_status.get(requirement.id, "not automated"),
            last_executed_at=last,
            stale=last is not None and (now or datetime.now(UTC)) - last > timedelta(days=self.stale_days),
            observed=observed,
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
        url=github_run_url(latest.url) if latest else None,
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


def _evidence(line: Sequence[HistoryExecution]) -> tuple[datetime | None, str | None, str | None]:
    """The runs behind a stability classification: last failure time, last failing and passing run."""
    failing = [e for e in line if e.result.outcome in (Outcome.FAILED, Outcome.ERROR)]
    passing = [e for e in line if e.result.outcome is Outcome.PASSED]
    return (
        failing[-1].run.started_at if failing else None,
        failing[-1].run.run_id if failing else None,
        passing[-1].run.run_id if passing else None,
    )


def _without_builds(scope: Scope) -> Scope:
    """The scope without its build filter (a build comparison chooses its builds itself)."""
    return Scope(filters=scope.filters, run_filters=replace(scope.run_filters, builds=frozenset()))


def _side_view(side: BuildSide, records: Sequence[PipelineCollection] = ()) -> BuildSideView:
    """One build of a comparison, with the GitHub runs of its pipelines."""
    coverage = side.coverage
    ids = {run.pipeline.pipeline_id for run in side.runs if run.pipeline}
    mine = [c for c in records if c.pipeline_id in ids]
    return BuildSideView(
        build=side.build,
        runs=len(side.runs),
        counts=side.counts,
        pass_rate=RatioView.of(side.pass_rate),
        last_started_at=side.last_started_at,
        requirement_coverage=RatioView.of(coverage.requirement_coverage) if coverage else None,
        automated_requirement_coverage=RatioView.of(coverage.automated_requirement_coverage)
        if coverage
        else None,
        ci_runs=tuple(
            sorted({f"{github_run_url(c.url)}/attempts/{c.attempt}" for c in mine if github_run_url(c.url)})
        ),
        incomplete_pipelines=tuple(
            sorted({f"{c.pipeline_id} attempt {c.attempt}" for c in mine if c.state == "incomplete"})
        ),
    )


def _execution_view(
    run: TestRun,
    result: TestResult,
    ci_urls: dict[str, str] | None = None,
    workflows: dict[str, str] | None = None,
) -> ExecutionView:
    """One execution with its run (and the CI run it came from, when collected)."""
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
        pipeline=run.pipeline,
        ci_url=(ci_urls or {}).get(run.pipeline.pipeline_id) if run.pipeline else None,
        workflow=(workflows or {}).get(run.pipeline.pipeline_id) if run.pipeline else None,
    )


def _with_repository(params: dict[str, str], repository: str | None) -> dict[str, str]:
    """Link parameters that keep the repository context when there is one."""
    return {**params, "repository": repository} if repository else params


def _context_label(context: tuple[str | None, ...]) -> str:
    """Framework / environment / browser / platform, '-' for missing parts."""
    return " / ".join(part or "-" for part in context)


def _sorted(values: Iterable[str | None]) -> tuple[str, ...]:
    """Distinct non-empty values, sorted."""
    return tuple(sorted({v for v in values if v}))


def _text(member: object) -> str:
    """Enum value, or ``unspecified``."""
    return UNSPECIFIED if member is None else str(getattr(member, "value", member))
