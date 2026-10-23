"""The readiness policy: unknown before blocked before at risk before ready."""

import pytest

from qualityintel.gates.config import GateConfig
from qualityintel.models.enums import Outcome
from qualityintel.readiness import Readiness, ReadinessState, readiness
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


def effects(state: Readiness) -> dict[str, tuple[str, str]]:
    """Scorecard as name -> (result, effect)."""
    return {c.name: (c.result, c.effect) for c in state.criteria}


def test_scorecard_without_a_gate_has_only_the_policy_rows() -> None:
    """No gate: its row is unknown and makes the status unknown; no gate rules to list."""
    state = readiness(report(Outcome.PASSED), None)

    assert effects(state) == {
        "release gate configured": ("unknown", "unknown"),
        "flaky candidates": ("pass", "none"),
        "incomplete pipeline collections (7 days)": ("pass", "none"),
        "data freshness": ("pass", "none"),
    }


def test_scorecard_shows_the_blocking_rule_and_the_warning_beside_it() -> None:
    """Blocked by the pass-rate rule; the flaky warning is listed as at risk."""
    state = readiness(report(Outcome.PASSED, Outcome.FAILED), GATE, flaky_candidates=1)

    rows = {c.name: c for c in state.criteria}
    rule = rows["execution pass rate"]
    assert (rule.source, rule.measured, rule.threshold, rule.result, rule.effect) == (
        "gate",
        "50.0 % (1/2)",
        ">= 100 %",
        "fail",
        "blocks",
    )
    assert effects(state)["flaky candidates"] == ("warning", "at risk")
    assert effects(state)["gate inputs complete"] == ("pass", "none")


def test_scorecard_on_incomplete_inputs_blocks_nothing_but_is_unknown() -> None:
    """Without results the gate cannot decide: its rules cannot block, the inputs row says why."""
    state = readiness(report(), GATE)

    inputs = next(c for c in state.criteria if c.name == "gate inputs complete")
    assert (inputs.result, inputs.effect) == ("unknown", "unknown")
    assert "no test results were read" in inputs.explanation
    assert "blocks" not in {c.effect for c in state.criteria}


def test_a_ready_scorecard_has_no_row_that_affects_the_status() -> None:
    """Ready means every row passed: the status can be checked against the rows."""
    state = readiness(report(Outcome.PASSED), GATE)

    assert state.state is ReadinessState.READY
    assert {c.effect for c in state.criteria} == {"none"}
    assert [c.name for c in state.criteria][:3] == [
        "release gate configured",
        "gate inputs complete",
        "execution pass rate",
    ]


@pytest.mark.parametrize(
    ("outcomes", "gate", "kwargs"),
    [
        ((Outcome.PASSED,), None, {}),
        ((), GATE, {"flaky_candidates": 1}),
        ((Outcome.FAILED,), GATE, {"stale": True}),
        ((Outcome.PASSED,), GATE, {"incomplete_pipelines": 2}),
        ((Outcome.PASSED,), GATE, {}),
    ],
    ids=["no-gate", "incomplete", "blocked", "at-risk", "ready"],
)
def test_the_status_can_be_read_from_the_scorecard_rows(
    outcomes: tuple[Outcome, ...], gate: GateConfig | None, kwargs: dict[str, object]
) -> None:
    """docs/readiness.md: any unknown row, else any blocks row, else any at-risk row, else ready."""
    state = readiness(report(*outcomes), gate, **kwargs)  # type: ignore[arg-type]

    found = {c.effect for c in state.criteria}
    derived = next(
        (
            s
            for effect, s in (("unknown", "unknown"), ("blocks", "blocked"), ("at risk", "at risk"))
            if effect in found
        ),
        "ready",
    )
    assert derived == state.state.value
