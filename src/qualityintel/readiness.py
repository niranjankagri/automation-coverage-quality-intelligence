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
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from qualityintel.gates.config import GateConfig
from qualityintel.gates.evaluate import GateResult, GateStatus, evaluate
from qualityintel.traceability.report import TraceabilityReport


class ReadinessState(StrEnum):
    """The overview's status."""

    READY = "ready"
    AT_RISK = "at risk"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class Readiness:
    """The status with every reason behind it."""

    state: ReadinessState
    reasons: tuple[str, ...]
    gate: GateResult | None


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
    if gate is None:
        return Readiness(
            ReadinessState.UNKNOWN,
            ("no release gate is configured, so there is no release decision", *warnings),
            None,
        )
    result = evaluate(report, gate, input_problems)
    if result.status is GateStatus.INCOMPLETE:
        reasons = [f"the gate cannot decide: {problem}" for problem in result.input_problems]
        return Readiness(ReadinessState.UNKNOWN, (*reasons, *warnings), result)
    if result.status is GateStatus.FAILED:
        reasons = [
            f"rule failed: {rule.name} ({rule.actual}, expected {rule.expected})"
            for rule in result.failed_rules
        ]
        return Readiness(ReadinessState.BLOCKED, (*reasons, *warnings), result)
    if warnings:
        return Readiness(ReadinessState.AT_RISK, ("the gate passed", *warnings), result)
    return Readiness(
        ReadinessState.READY,
        ("the gate passed; no flaky candidates, incomplete pipelines or stale data",),
        result,
    )
