"""The gate over time: one verdict per day's snapshot, changes when the verdict or reasons change."""

import pytest

from qualityintel.gates.config import GateConfig
from qualityintel.gates.evaluate import GateStatus
from qualityintel.gates.history import gate_history
from qualityintel.models.enums import Outcome

from .traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit

P, F = Outcome.PASSED, Outcome.FAILED
CATALOG = catalog([req("R1", criticality="critical")], [case("TC", "R1", automated_by=("suite::*",))])
GATE = GateConfig.model_validate(
    {"execution": {"min_pass_rate": 100, "max_failed_tests": 0, "min_results": 2}}
)


def test_one_verdict_per_day_from_that_days_snapshot() -> None:
    """Day 18 passes, day 19 fails, day 20 the suite passes again: three verdicts, two changes."""
    runs = [run(result("a", P), result("b", P), day=18), run(result("a", F), result("b", P), day=19)]
    runs.append(run(result("a", P), result("b", P), day=20))

    days, changes = gate_history(runs, CATALOG, GATE)

    assert [(d.day.day, d.status) for d in days] == [
        (18, GateStatus.PASSED),
        (19, GateStatus.FAILED),
        (20, GateStatus.PASSED),
    ]
    assert days[1].failed_rules == ("execution pass rate", "failed tests")
    assert days[1].latest_run_id == runs[1].run_id
    assert [(c.day.day, c.previous, c.status) for c in changes] == [
        (19, GateStatus.PASSED, GateStatus.FAILED),
        (20, GateStatus.FAILED, GateStatus.PASSED),
    ]
    assert changes[0].started_failing == ("execution pass rate", "failed tests")
    assert changes[1].stopped_failing == ("execution pass rate", "failed tests")


def test_a_changed_reason_is_a_change_even_if_the_verdict_stays_failed() -> None:
    """Failed on both days, but for a different rule: listed, with what started and stopped."""
    runs = [
        run(result("a", F), result("b", P), day=18),  # 2 results, 1 failed
        run(result("a", P), day=19, browser="other"),
    ]
    # day 19: the day-18 suite is carried over (still failing) and a second suite is added, so
    # the snapshot has 3 results: "executed tests" passes, "failed tests" still fails
    gate = GateConfig.model_validate({"execution": {"max_failed_tests": 0, "min_results": 3}})

    _, changes = gate_history(runs, CATALOG, gate)

    (change,) = changes
    assert (change.previous, change.status) == (GateStatus.FAILED, GateStatus.FAILED)
    assert change.stopped_failing == ("executed tests",)
    assert change.started_failing == ()


def test_days_without_a_change_are_not_changes() -> None:
    """Same verdict, same failing rules: no change."""
    runs = [run(result("a", P), result("b", P), day=d) for d in (18, 19, 20)]

    days, changes = gate_history(runs, CATALOG, GATE)

    assert len(days) == 3
    assert changes == ()


def test_only_the_last_days_are_kept_and_undated_runs_take_no_part() -> None:
    """``days`` limits the history; an undated run cannot be placed on a day."""
    runs = [run(result("a", P), result("b", P), day=d) for d in range(1, 11)]
    runs.append(run(result("a", F), day=None))

    days, _ = gate_history(runs, CATALOG, GATE, days=3)

    assert [d.day.day for d in days] == [8, 9, 10]
    assert all(d.status is GateStatus.PASSED for d in days)


def test_an_empty_history_has_no_days() -> None:
    """Nothing to evaluate: no days, no changes (not a passed gate)."""
    assert gate_history([], CATALOG, GATE) == ((), ())
