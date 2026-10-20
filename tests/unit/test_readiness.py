"""The readiness policy: unknown before blocked before at risk before ready."""

import pytest

from qualityintel.gates.config import GateConfig
from qualityintel.models.enums import Outcome
from qualityintel.readiness import ReadinessState, readiness
from qualityintel.traceability.report import TraceabilityReport, build_report

from .traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit

CATALOG = catalog([req("R1", criticality="critical")], [case("TC", "R1", automated_by=("suite::*",))])
GATE = GateConfig.model_validate({"name": "release", "execution": {"min_pass_rate": 100}})


def report(*outcomes: Outcome) -> TraceabilityReport:
    """A report with one run holding these outcomes (none: no runs at all)."""
    runs = [run(*(result(f"t{i}", o) for i, o in enumerate(outcomes)))] if outcomes else []
    return build_report(CATALOG, runs)


def test_no_gate_is_unknown_even_with_a_perfect_pass_rate() -> None:
    """100 % passed is not a release decision."""
    state = readiness(report(Outcome.PASSED), None)

    assert state.state is ReadinessState.UNKNOWN
    assert "no release gate is configured" in state.reasons[0]


def test_missing_results_are_unknown_not_ready() -> None:
    """The gate cannot decide without results: unknown, with the gate's reason."""
    state = readiness(report(), GATE)

    assert state.state is ReadinessState.UNKNOWN
    assert "no test results were read" in state.reasons[0]


def test_a_failed_rule_blocks_and_names_the_rule() -> None:
    """Blocked, with actual and expected values."""
    state = readiness(report(Outcome.PASSED, Outcome.FAILED), GATE)

    assert state.state is ReadinessState.BLOCKED
    assert state.reasons[0] == "rule failed: execution pass rate (50.0 % (1/2), expected >= 100 %)"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"flaky_candidates": 2}, "2 flaky candidate(s)"),
        ({"incomplete_pipelines": 1}, "1 incomplete pipeline collection(s)"),
        ({"stale": True}, "could not be refreshed"),
    ],
)
def test_a_passed_gate_with_warnings_is_at_risk(kwargs: dict[str, object], reason: str) -> None:
    """The gate passed, but something it does not measure needs attention."""
    state = readiness(report(Outcome.PASSED), GATE, **kwargs)  # type: ignore[arg-type]

    assert state.state is ReadinessState.AT_RISK
    assert any(reason in r for r in state.reasons)


def test_ready_only_when_the_gate_passed_and_nothing_else_is_wrong() -> None:
    """The one path to ready."""
    state = readiness(report(Outcome.PASSED), GATE)

    assert state.state is ReadinessState.READY
    assert state.gate is not None


def test_warnings_are_kept_next_to_a_blocking_reason() -> None:
    """A blocked scope still lists its flaky candidates."""
    state = readiness(report(Outcome.FAILED), GATE, flaky_candidates=1)

    assert state.state is ReadinessState.BLOCKED
    assert any("flaky" in r for r in state.reasons)
