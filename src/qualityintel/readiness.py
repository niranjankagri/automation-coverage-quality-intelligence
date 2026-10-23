"""Release readiness: one status for the overview, derived from the release gate (docs/readiness.md).

The policy, in this order:

1. **Unknown**: no release gate is configured, or the gate cannot decide (results missing,
   unreadable or empty; an incomplete pipeline). Missing evidence is never shown as ready.
2. **Blocked**: the gate decided and a rule failed.
3. **At risk**: the gate passed, but something the gate does not measure needs attention:
   flaky candidates in the scope, incomplete pipeline collections in the last 7 days, or data
   that could not be refreshed (stale).
4. **Ready**: the gate passed and none of the above applies.

A high pass rate alone never makes a scope ready: readiness is the gate's decision plus the
warnings above, each listed as a reason.

The **scorecard** (M13) lists every criterion the status was derived from, one row each: the
gate's presence and inputs, every gate rule, and the three warnings. Each row says what was
measured, the threshold, its result and its effect on the status, so the status can be checked
by hand against the rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from qualityintel.gates.config import GateConfig
from qualityintel.gates.evaluate import GateResult, GateStatus, RuleStatus, evaluate
from qualityintel.traceability.report import TraceabilityReport


class ReadinessState(StrEnum):
    """The overview's status."""

    READY = "ready"
    AT_RISK = "at risk"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Criterion:
    """One scorecard row: a criterion the status depends on.

    Attributes:
        source: ``"gate"`` for the release gate and its rules, ``"policy"`` for the warnings the
            gate does not measure.
        result: ``pass``, ``fail``, ``warning`` or ``unknown``.
        effect: What the row does to the status: ``blocks``, ``at risk``, ``unknown`` or ``none``.
    """

    name: str
    source: str
    measured: str
    threshold: str
    result: str
    effect: str
    explanation: str


@dataclass(frozen=True)
class Readiness:
    """The status with every reason behind it and the scorecard it was derived from."""

    state: ReadinessState
    reasons: tuple[str, ...]
    gate: GateResult | None
    criteria: tuple[Criterion, ...] = ()


def readiness(
    report: TraceabilityReport,
    gate: GateConfig | None,
    flaky_candidates: int = 0,
    incomplete_pipelines: int = 0,
    stale: bool = False,
    input_problems: Sequence[str] = (),
) -> Readiness:
    """Apply the policy to one scope's report.

    Args:
        report: Coverage and execution of the scope.
        gate: The release gate; ``None`` when none is configured.
        flaky_candidates: Flaky candidates in the scope (history analysis).
        incomplete_pipelines: Incomplete pipeline collections in the scope, last 7 days.
        stale: The data could not be refreshed from its sources.
        input_problems: Known problems with the inputs (passed to the gate).
    """
    warnings = []
    if flaky_candidates:
        warnings.append(f"{flaky_candidates} flaky candidate(s) in the scope (Stability page)")
    if incomplete_pipelines:
        warnings.append(f"{incomplete_pipelines} incomplete pipeline collection(s) in the last 7 days")
    if stale:
        warnings.append("the data could not be refreshed: the figures may be outdated")
    result = evaluate(report, gate, input_problems) if gate is not None else None
    criteria = scorecard(result, flaky_candidates, incomplete_pipelines, stale)
    if result is None:
        return Readiness(
            ReadinessState.UNKNOWN,
            ("no release gate is configured, so there is no release decision", *warnings),
            None,
            criteria,
        )
    if result.status is GateStatus.INCOMPLETE:
        reasons = [f"the gate cannot decide: {problem}" for problem in result.input_problems]
        return Readiness(ReadinessState.UNKNOWN, (*reasons, *warnings), result, criteria)
    if result.status is GateStatus.FAILED:
        reasons = [
            f"rule failed: {rule.name} ({rule.actual}, expected {rule.expected})"
            for rule in result.failed_rules
        ]
        return Readiness(ReadinessState.BLOCKED, (*reasons, *warnings), result, criteria)
    if warnings:
        return Readiness(ReadinessState.AT_RISK, ("the gate passed", *warnings), result, criteria)
    return Readiness(
        ReadinessState.READY,
        ("the gate passed; no flaky candidates, incomplete pipelines or stale data",),
        result,
        criteria,
    )


def scorecard(
    gate: GateResult | None, flaky_candidates: int, incomplete_pipelines: int, stale: bool
) -> tuple[Criterion, ...]:
    """Every criterion of the policy as a row, in the order the policy checks them."""
    rows = [
        Criterion(
            "release gate configured",
            "gate",
            gate.config.name if gate else "none",
            "a gate is configured",
            "pass" if gate else "unknown",
            "none" if gate else "unknown",
            "without a gate there is no release decision",
        )
    ]
    if gate is not None:
        incomplete = gate.status is GateStatus.INCOMPLETE
        rows.append(
            Criterion(
                "gate inputs complete",
                "gate",
                f"{len(gate.input_problems)} problem(s)" if incomplete else "complete",
                "results present, readable, not empty; pipeline complete",
                "unknown" if incomplete else "pass",
                "unknown" if incomplete else "none",
                "; ".join(gate.input_problems) or "the gate can decide on these inputs",
            )
        )
        for rule in gate.rules:
            failing = rule.counts_as_failure
            rows.append(
                Criterion(
                    rule.name,
                    "gate",
                    rule.actual,
                    rule.expected,
                    "fail"
                    if failing
                    else ("pass" if rule.status is RuleStatus.PASSED else rule.status.value),
                    # A rule only blocks once the gate can decide; on incomplete inputs it is unknown
                    ("unknown" if incomplete else "blocks") if failing else "none",
                    rule.explanation,
                )
            )
    rows += [
        _warning(
            "flaky candidates",
            str(flaky_candidates),
            bool(flaky_candidates),
            "tests with mixed outcomes the gate does not measure (history rules, docs/history.md)",
        ),
        _warning(
            "incomplete pipeline collections (7 days)",
            str(incomplete_pipelines),
            bool(incomplete_pipelines),
            "collections with missing jobs or reports in the last 7 days (docs/collection.md)",
        ),
        Criterion(
            "data freshness",
            "policy",
            "stale" if stale else "fresh",
            "fresh",
            "warning" if stale else "pass",
            "at risk" if stale else "none",
            "the dashboard could refresh its data from its sources",
        ),
    ]
    return tuple(rows)


def _warning(name: str, measured: str, raised: bool, explanation: str) -> Criterion:
    """A policy warning: 0 passes, anything else puts a passed gate at risk."""
    return Criterion(
        name,
        "policy",
        measured,
        "0",
        "warning" if raised else "pass",
        "at risk" if raised else "none",
        explanation,
    )
