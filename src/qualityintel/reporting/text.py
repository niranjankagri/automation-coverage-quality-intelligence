"""Plain-text rendering of a traceability report for the terminal and CI logs."""

from __future__ import annotations

from collections.abc import Iterable

from qualityintel.models.enums import Outcome
from qualityintel.traceability.coverage import CoverageNumbers
from qualityintel.traceability.report import TraceabilityReport

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
