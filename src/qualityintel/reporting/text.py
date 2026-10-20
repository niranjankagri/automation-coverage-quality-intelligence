"""Plain-text rendering of traceability and history reports for the terminal and CI logs."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from qualityintel.history.analysis import (
    ContextKey,
    DurationRegression,
    RecurringFailure,
    RunComparison,
    RunPoint,
    SlowTest,
    Stability,
    TestStability,
)
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio
from qualityintel.models.results import TestRun
from qualityintel.traceability.coverage import CoverageNumbers
from qualityintel.traceability.report import TraceabilityReport, context_key

WIDTH = 96


def render_traceability(report: TraceabilityReport, with_execution: bool = True) -> str:
    """Totals, gaps, breakdowns and (when runs were given) the execution snapshot."""
    coverage = report.coverage
    lines = [
        "COVERAGE",
        *_metric_lines(coverage.totals, indent="  "),
        "",
        "GAPS",
        *_list("requirements without tests", [r.id for r in coverage.requirements_without_tests]),
        *_list("requirements without automation", [r.id for r in coverage.requirements_without_automation]),
        *_list("critical requirements without automation", [r.id for r in coverage.uncovered_critical]),
        *_list(
            "automated test cases linked to no requirement", [c.id for c in coverage.unlinked_automated_cases]
        ),
    ]
    for title, groups in (
        ("BY FEATURE", coverage.by_feature),
        ("BY CRITICALITY", coverage.by_criticality),
        ("BY TEST TYPE", coverage.by_test_type),
        ("BY PLATFORM", coverage.by_platform),
    ):
        lines += ["", title, *_breakdown(groups)]
    if with_execution:
        lines += ["", *_execution(report)]
    return "\n".join(lines) + "\n"


def _metric_lines(numbers: CoverageNumbers, indent: str) -> list[str]:
    """The three catalog metrics, one per line."""
    return [
        f"{indent}requirement coverage            {numbers.requirement_coverage}",
        f"{indent}automation coverage (cases)     {numbers.automation_coverage}",
        f"{indent}automated requirement coverage  {numbers.automated_requirement_coverage}",
    ]


def _breakdown(groups: dict[str, CoverageNumbers]) -> list[str]:
    """One row per group: the three metrics side by side."""
    if not groups:
        return ["  (nothing in scope)"]
    rows = [f"  {'':<26} {'requirement cov.':<22} {'automation cov.':<22} automated req. cov."]
    for name, numbers in groups.items():
        rows.append(
            f"  {name[:26]:<26} {numbers.requirement_coverage!s:<22} {numbers.automation_coverage!s:<22} "
            f"{numbers.automated_requirement_coverage!s}"
        )
    return rows


def _execution(report: TraceabilityReport) -> list[str]:
    """Snapshot runs, outcome counts, pass rate and requirement statuses."""
    if not report.snapshot:
        return ["EXECUTION", "  no result files given: execution status not evaluated"]
    counts = report.outcome_counts
    statuses: dict[str, int] = {}
    for status in report.requirement_status.values():
        statuses[status] = statuses.get(status, 0) + 1
    lines = [
        "EXECUTION (latest run per framework / environment / browser / platform)",
        *(
            f"  {run.source[-60:]:<60} {run.context.framework or '-'}/{run.context.browser or '-'}"
            for run in report.snapshot
        ),
        f"  results: {counts[Outcome.PASSED]} passed, {counts[Outcome.FAILED]} failed, "
        f"{counts[Outcome.ERROR]} error, {counts[Outcome.SKIPPED]} skipped",
        f"  execution pass rate             {report.pass_rate}",
        "  requirements: " + ", ".join(f"{count} {status}" for status, count in sorted(statuses.items())),
        *_list("failing critical requirements", list(report.failing_critical)),
        *_list(
            "failing requirements",
            [rid for rid, status in report.requirement_status.items() if status == "failing"],
        ),
        *_list("automated test cases without results", list(report.automated_cases_without_results)),
        f"  results matching no test case   {len(report.unmatched)}",
    ]
    if report.unknown_ids:
        lines += _list("test ids not in the catalog", sorted(report.unknown_ids))
    return lines


def _list(title: str, items: Iterable[str]) -> list[str]:
    """``title (n): a, b, c`` wrapped to the report width; ``none`` when empty."""
    items = list(items)
    head = f"  {title} ({len(items)}): "
    if not items:
        return [head + "none"]
    lines: list[str] = []
    current = head
    for index, item in enumerate(items):
        piece = item + (", " if index < len(items) - 1 else "")
        if len(current) + len(piece) > WIDTH and current.strip():
            lines.append(current.rstrip())
            current = " " * 4
        current += piece
    lines.append(current)
    return lines


def render_history(
    stability: list[TestStability],
    recurring: list[RecurringFailure],
    errors: dict[str, int],
    regressions: list[DurationRegression],
    slowest: list[SlowTest],
    trends: dict[ContextKey, list[RunPoint]],
    by_build: dict[str, tuple[int, Ratio]],
    last_points: int = 8,
) -> str:
    """History report: stability classes with evidence, failures, durations, trends."""
    counts: dict[str, int] = {}
    for row in stability:
        counts[row.status.value] = counts.get(row.status.value, 0) + 1
    lines = [
        "STABILITY (per test and run context, last verdicts in the window)",
        "  " + (", ".join(f"{n} {status}" for status, n in sorted(counts.items())) or "no executions"),
    ]
    for status in (
        Stability.CONSISTENTLY_FAILING,
        Stability.NEW_FAILURE,
        Stability.FLAKY_CANDIDATE,
        Stability.RECOVERED,
    ):
        rows = [r for r in stability if r.status is status]
        lines += ["", f"{status.value.upper()} ({len(rows)})"]
        lines += [
            f"  {r.key}\n    {_context(r.context)} · failure rate {r.failure_rate} · {'; '.join(r.reasons)}"
            for r in rows
        ] or ["  none"]
    lines += ["", f"RECURRING FAILURES ({len(recurring)})"]
    lines += [
        f"  {f.signature}\n    {f.occurrences} times in {f.runs} runs, {len(f.tests)} test(s)"
        for f in recurring
    ] or ["  none"]
    lines += ["", f"TESTS WITH ERRORS IN SEVERAL RUNS ({len(errors)})"]
    lines += [f"  {key}: {n} runs" for key, n in errors.items()] or ["  none"]
    lines += ["", f"DURATION REGRESSIONS ({len(regressions)})"]
    lines += [
        f"  {r.key}\n    {_context(r.context)} · {r.baseline_seconds:.2f} s -> {r.latest_seconds:.2f} s "
        f"(+{r.increase:.0%}, baseline of {r.baseline_runs} runs)"
        for r in regressions
    ] or ["  none"]
    lines += ["", "SLOWEST TESTS (median)"]
    lines += [f"  {t.median_seconds:8.2f} s  {t.key}  [{_context(t.context)}]" for t in slowest] or ["  none"]
    lines += ["", f"TREND (last {last_points} runs per context: pass rate, failed+error)"]
    for context, points in trends.items():
        recent = points[-last_points:]
        lines.append(f"  {_context(context)}")
        lines += [
            f"    {_day(p.run.started_at)}  {p.run.context.build or '-':<9} {p.pass_rate!s:<20} "
            f"{p.failed:>3} failed"
            for p in recent
        ]
    lines += ["", "BY BUILD (runs, pooled pass rate)"]
    lines += [f"  {build:<12} {runs:>3} runs  {rate}" for build, (runs, rate) in by_build.items()] or [
        "  none"
    ]
    return "\n".join(lines) + "\n"


def render_comparison(base: TestRun, head: TestRun, diff: RunComparison) -> str:
    """Differences between two runs."""
    lines = [f"BASE {base.source}  ({_day(base.started_at)}, build {base.context.build or '-'})"]
    lines.append(f"HEAD {head.source}  ({_day(head.started_at)}, build {head.context.build or '-'})")
    if context_key(base.context) != context_key(head.context):
        lines.append("note: the runs have different contexts; differences may come from the environment")
    for title, items in (
        ("NEWLY FAILING", diff.newly_failing),
        ("FIXED", diff.fixed),
        ("STILL FAILING", diff.still_failing),
        ("ADDED", diff.added),
        ("REMOVED", diff.removed),
    ):
        lines += (
            ["", f"{title} ({len(items)})", *(f"  {key}" for key in items)] if items else ["", f"{title} (0)"]
        )
    lines += ["", f"CLEARLY SLOWER ({len(diff.slower)})"]
    lines += [f"  {old:.2f} s -> {new:.2f} s  {key}" for key, old, new in diff.slower]
    return "\n".join(lines) + "\n"


def _context(context: ContextKey) -> str:
    """framework/environment/browser/platform with '-' for missing parts."""
    return "/".join(part or "-" for part in context)


def _day(moment: datetime | None) -> str:
    """Start time as text."""
    return moment.strftime("%Y-%m-%d %H:%M") if moment else "undated         "
