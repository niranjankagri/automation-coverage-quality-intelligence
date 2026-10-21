"""Needs attention: the evidence rules (docs/attention.md)."""

from datetime import UTC, datetime

import pytest

from qualityintel.attention import (
    OPEN,
    RESOLVED,
    UNKNOWN,
    latest_outcomes,
    newly_failing,
    pipeline_states,
    recurring_state,
)
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob, TestRun

from .traceability.helpers import result, run

pytestmark = pytest.mark.unit

P, F, E = Outcome.PASSED, Outcome.FAILED, Outcome.ERROR


def job(r: TestRun, pipeline: str, attempt: int = 1) -> TestRun:
    """The run as attempt ``attempt`` of a pipeline job."""
    return r.model_copy(
        update={"pipeline": PipelineJob(pipeline_id=pipeline, job="ui", attempt=attempt, repository="o/r")}
    )


def test_a_test_that_passed_before_and_fails_now_is_newly_failing() -> None:
    """Latest execution of the suite vs the previous one: pass -> fail and pass -> error."""
    before = job(run(result("a", P), result("b", P), result("c", F), day=18), "r#1")
    now = job(run(result("a", F), result("b", E), result("c", F), result("d", F), day=19), "r#2")

    found = newly_failing([before, now])

    assert [f.key for f in found] == ["suite::a", "suite::b"]  # c already failed; d is new
    assert found[0].previous_run is before


def test_a_rerun_that_passed_is_a_newer_execution() -> None:
    """Attempt 1 failed, attempt 2 passed: nothing is newly failing."""
    yesterday = job(run(result("a", P), day=18), "r#1")
    first = job(run(result("a", F), day=19, hour=9), "r#2", attempt=1)
    rerun = job(run(result("a", P), day=19, hour=10), "r#2", attempt=2)

    assert newly_failing([yesterday, first, rerun]) == []


def test_one_execution_alone_has_nothing_to_compare() -> None:
    """A failing test in a suite's only execution is not 'newly' failing."""
    assert newly_failing([job(run(result("a", F), day=19), "r#1")]) == []


def test_latest_outcome_is_the_last_execution_per_key() -> None:
    """Over several executions, the newest wins."""
    runs = [job(run(result("a", F), day=18), "r#1"), job(run(result("a", P), day=19), "r#2")]

    assert latest_outcomes(runs)["suite::a"][0] is P


def record(pipeline: str, day: int, state: str) -> PipelineCollection:
    """A collection record of repository o/r, workflow ci.yml."""
    return PipelineCollection(
        pipeline_id=pipeline,
        attempt=1,
        repository="o/r",
        workflow="ci.yml",
        run_number=day,
        branch="main",
        commit="abc1234",
        conclusion="cancelled" if state == "incomplete" else "success",
        url=f"https://github.com/o/r/actions/runs/{day}",
        started_at=datetime(2026, 10, day, tzinfo=UTC),
        collected_at=datetime(2026, 10, day, 1, tzinfo=UTC),
        state=state,  # type: ignore[arg-type]
        runs=0,
        results=0,
        problems=("job ui: artifact missing",) if state == "incomplete" else (),
    )


def test_an_incomplete_pipeline_is_open_until_a_later_complete_run() -> None:
    """Resolved by a later complete run of the same workflow; the latest incomplete one stays open."""
    states = pipeline_states(
        [record("r#1", 17, "incomplete"), record("r#2", 18, "complete"), record("r#3", 19, "incomplete")]
    )

    assert [(s.record.pipeline_id, s.state) for s in states] == [("r#1", RESOLVED), ("r#3", OPEN)]
    assert states[0].resolved_by is not None
    assert states[0].resolved_by.pipeline_id == "r#2"


@pytest.mark.parametrize(
    ("latest", "expected"),
    [
        ({"a": (F, None), "b": (P, None)}, OPEN),
        ({"a": (P, None), "b": (P, None)}, RESOLVED),
        ({"a": (Outcome.SKIPPED, None)}, UNKNOWN),
        ({}, UNKNOWN),
    ],
    ids=["one-still-fails", "all-pass-now", "only-skipped", "no-evidence"],
)
def test_a_recurring_failure_is_open_while_a_test_still_fails(
    latest: dict[str, tuple[Outcome, datetime | None]], expected: str
) -> None:
    """Never 'open' without a current failure, never 'resolved' without a pass."""
    assert recurring_state(["a", "b"], latest) == expected
