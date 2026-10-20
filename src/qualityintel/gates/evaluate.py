"""Evaluate a gate configuration against a traceability report.

A gate ends in one of three states, each with its own exit code (docs/quality-gates.md):

- ``passed`` (0): every configured rule passed;
- ``failed`` (1): at least one rule failed;
- ``incomplete`` (3): the input cannot support a decision (result files missing, unreadable
  or empty although execution rules are configured). Rules are still listed for the report,
  but the verdict is never "passed".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from qualityintel.gates.config import GateConfig
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio
from qualityintel.traceability.report import FAILING, TraceabilityReport


class GateStatus(StrEnum):
    """Final verdict of a gate."""

    PASSED = "passed"
    FAILED = "failed"
    INCOMPLETE = "incomplete"


class RuleStatus(StrEnum):
    """Result of one rule."""

    PASSED = "passed"
    FAILED = "failed"
    NOT_APPLICABLE = "not applicable"  # metric had a zero denominator; counts per config


EXIT_CODES = {GateStatus.PASSED: 0, GateStatus.FAILED: 1, GateStatus.INCOMPLETE: 3}


@dataclass(frozen=True)
class RuleResult:
    """One configured rule with what was measured.

    Attributes:
        actual: Measured value as shown to people (``"92.9 % (39/42)"`` or ``"2"``).
        expected: The threshold as text (``">= 95 %"``, ``"<= 0"``).
        items: What caused a failure (requirement ids, test keys), for the report.
        counts_as_failure: Whether this rule makes the gate fail (a ``not applicable`` rule
            fails unless the config says ``not_applicable = "pass"``).
    """

    name: str
    status: RuleStatus
    actual: str
    expected: str
    explanation: str
    items: tuple[str, ...] = ()
    counts_as_failure: bool = False


@dataclass
class GateResult:
    """Verdict, rules and the problems with the input."""

    config: GateConfig
    status: GateStatus
    rules: list[RuleResult]
    input_problems: list[str] = field(default_factory=list)

    @property
    def exit_code(self) -> int:
        """Process exit code for CI."""
        return EXIT_CODES[self.status]

    @property
    def failed_rules(self) -> list[RuleResult]:
        """Rules that make the gate fail."""
        return [rule for rule in self.rules if rule.counts_as_failure]


def evaluate(
    report: TraceabilityReport, config: GateConfig, input_problems: Sequence[str] = ()
) -> GateResult:
    """Apply every configured rule; decide passed, failed or incomplete.

    Args:
        report: Coverage and execution status for the gate's scope.
        config: The gate definition.
        input_problems: Errors found while reading inputs (unreadable files, patterns that
            matched nothing). Any problem makes the gate incomplete.
    """
    problems = list(input_problems)
    if config.needs_results and not report.snapshot:
        problems.append("execution rules are configured but no test results were read")
    elif config.needs_results and sum(report.outcome_counts.values()) == 0:
        problems.append("the result files contain no test results")

    rules = [*_coverage_rules(report, config), *_execution_rules(report, config)]
    if problems:
        status = GateStatus.INCOMPLETE
    elif any(rule.counts_as_failure for rule in rules):
        status = GateStatus.FAILED
    else:
        status = GateStatus.PASSED
    return GateResult(config=config, status=status, rules=rules, input_problems=problems)


def _coverage_rules(report: TraceabilityReport, config: GateConfig) -> list[RuleResult]:
    """Rules on catalog metrics."""
    rules = config.coverage
    totals = report.coverage.totals
    results = []
    for name, threshold, ratio, explanation in (
        (
            "requirement coverage",
            rules.min_requirement_coverage,
            totals.requirement_coverage,
            "requirements with at least one linked test case",
        ),
        (
            "automation coverage",
            rules.min_automation_coverage,
            totals.automation_coverage,
            "linked test cases that are automated",
        ),
        (
            "automated requirement coverage",
            rules.min_automated_requirement_coverage,
            totals.automated_requirement_coverage,
            "requirements with at least one automated test case",
        ),
    ):
        if threshold is not None:
            results.append(_min_ratio(name, ratio, threshold, explanation, config))
    if rules.max_uncovered_critical is not None:
        items = tuple(r.id for r in report.coverage.uncovered_critical)
        results.append(
            _max_count(
                "critical requirements without automation",
                items,
                rules.max_uncovered_critical,
                "critical requirements with no automated test case",
            )
        )
    if rules.max_requirements_without_tests is not None:
        items = tuple(r.id for r in report.coverage.requirements_without_tests)
        results.append(
            _max_count(
                "requirements without tests",
                items,
                rules.max_requirements_without_tests,
                "requirements with no linked test case at all",
            )
        )
    return results


def _execution_rules(report: TraceabilityReport, config: GateConfig) -> list[RuleResult]:
    """Rules on the execution snapshot."""
    rules = config.execution
    counts = report.outcome_counts
    results = []
    if rules.min_pass_rate is not None:
        results.append(
            _min_ratio(
                "execution pass rate",
                report.pass_rate,
                rules.min_pass_rate,
                "passed of passed + failed + error, latest run per context",
                config,
            )
        )
    if rules.max_failing_critical is not None:
        results.append(
            _max_count(
                "failing critical requirements",
                report.failing_critical,
                rules.max_failing_critical,
                "critical requirements with a failing automated test",
            )
        )
    if rules.max_failing_requirements is not None:
        failing = tuple(rid for rid, status in report.requirement_status.items() if status == FAILING)
        results.append(
            _max_count(
                "failing requirements",
                failing,
                rules.max_failing_requirements,
                "requirements with a failing automated test",
            )
        )
    if rules.max_failed_tests is not None:
        failed = tuple(
            sorted(
                {
                    result.key
                    for run in report.snapshot
                    for result in run.results
                    if result.outcome in (Outcome.FAILED, Outcome.ERROR)
                }
            )
        )
        results.append(
            _max_count("failed tests", failed, rules.max_failed_tests, "tests that failed or errored")
        )
    if rules.min_results is not None:
        verdicts = counts[Outcome.PASSED] + counts[Outcome.FAILED] + counts[Outcome.ERROR]
        ok = verdicts >= rules.min_results
        results.append(
            RuleResult(
                name="executed tests",
                status=RuleStatus.PASSED if ok else RuleStatus.FAILED,
                actual=str(verdicts),
                expected=f">= {rules.min_results}",
                explanation="tests with a verdict; catches a suite that silently ran fewer tests",
                counts_as_failure=not ok,
            )
        )
    if rules.max_automated_cases_without_results is not None:
        results.append(
            _max_count(
                "automated test cases without results",
                report.automated_cases_without_results,
                rules.max_automated_cases_without_results,
                "automated test cases that no result matched (renamed, deleted or not run)",
            )
        )
    return results


def _min_ratio(name: str, ratio: Ratio, threshold: float, explanation: str, config: GateConfig) -> RuleResult:
    """``ratio >= threshold %``; n/a follows ``config.not_applicable``. Compares unrounded values."""
    expected = f">= {threshold:g} %"
    if ratio.value is None:
        fails = config.not_applicable == "fail"
        return RuleResult(
            name,
            RuleStatus.NOT_APPLICABLE,
            str(ratio),
            expected,
            f"{explanation}; nothing to measure (not_applicable = {config.not_applicable})",
            counts_as_failure=fails,
        )
    ok = ratio.value * 100 >= threshold
    return RuleResult(
        name,
        RuleStatus.PASSED if ok else RuleStatus.FAILED,
        str(ratio),
        expected,
        explanation,
        counts_as_failure=not ok,
    )


def _max_count(name: str, items: Sequence[str], limit: int, explanation: str) -> RuleResult:
    """``len(items) <= limit``; the items are listed in the report."""
    ok = len(items) <= limit
    return RuleResult(
        name,
        RuleStatus.PASSED if ok else RuleStatus.FAILED,
        str(len(items)),
        f"<= {limit}",
        explanation,
        items=tuple(items),
        counts_as_failure=not ok,
    )
