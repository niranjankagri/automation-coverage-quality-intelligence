"""Repository trends: each repository's snapshot on the newest day against 7 days earlier."""

import pytest

from qualityintel.history.trends import repository_trends
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob, TestRun

from ..traceability.helpers import result, run

pytestmark = pytest.mark.unit

P, F = Outcome.PASSED, Outcome.FAILED


def repo_run(repository: str, day: int, *outcomes: tuple[str, Outcome], job: str = "test") -> TestRun:
    """A run of ``job`` in ``repository`` on 2026-10-<day> with (test, outcome) pairs."""
    pipeline = PipelineJob(pipeline_id=f"{repository}-{day}", job=job, repository=repository)
    return run(*(result(name, o) for name, o in outcomes), day=day).model_copy(update={"pipeline": pipeline})


def test_now_is_set_against_seven_days_earlier_with_the_tests_that_changed() -> None:
    """o/a: day 12 all pass, day 19 'x' fails and 'y' recovered: one newly failing, one fixed."""
    runs = [
        repo_run("o/a", 12, ("x", P), ("y", F)),
        repo_run("o/a", 19, ("x", F), ("y", P)),
    ]

    today, (trend,) = repository_trends(runs)

    assert today is not None
    assert today.day == 19
    assert trend.before is not None
    assert (trend.before.day.day, trend.before.failed, trend.now.failed) == (12, 1, 1)
    assert (trend.newly_failing, trend.fixed) == (("suite::x",), ("suite::y",))
    assert trend.now.latest_run_id == runs[1].run_id


def test_the_earlier_day_uses_the_latest_runs_up_to_that_day() -> None:
    """A run on day 10 is the 'before' snapshot of day 17 (nothing ran on day 10..12 exactly)."""
    runs = [repo_run("o/a", 10, ("x", P)), repo_run("o/a", 17, ("x", P)), repo_run("o/a", 19, ("x", P))]

    _, (trend,) = repository_trends(runs)

    assert trend.before is not None
    assert (trend.before.day.day, trend.before.latest_run_id) == (12, runs[0].run_id)


def test_a_new_repository_has_no_earlier_snapshot() -> None:
    """Nothing ran in o/b before day 18: 'before' is None and every failure counts as new."""
    runs = [repo_run("o/a", 10, ("x", P)), repo_run("o/b", 18, ("x", F)), repo_run("o/a", 19, ("x", P))]

    _, trends = repository_trends(runs)

    by_name = {t.repository: t for t in trends}
    assert by_name["o/b"].before is None
    assert by_name["o/b"].newly_failing == ("suite::x",)


def test_repositories_with_new_failures_come_first_then_the_largest_drop() -> None:
    """o/c gained a failure; o/b dropped 50 points without a new key; o/a is unchanged."""
    runs = [
        repo_run("o/a", 12, ("x", P)),
        repo_run("o/a", 19, ("x", P)),
        repo_run("o/b", 12, ("x", F), ("y", P), ("z", P), ("w", P)),
        repo_run("o/b", 19, ("x", F), ("y", P)),
        repo_run("o/c", 12, ("x", P)),
        repo_run("o/c", 19, ("x", F), ("y", P)),
    ]

    _, trends = repository_trends(runs)

    assert [t.repository for t in trends] == ["o/c", "o/b", "o/a"]


def test_only_dated_pipeline_runs_with_a_repository_take_part() -> None:
    """A file imported by hand (no pipeline) or an undated run has no repository trend."""
    runs = [run(result("x", F), day=19), repo_run("o/a", 19, ("x", P))]
    runs.append(run(result("x", F), day=None).model_copy(update={"pipeline": runs[1].pipeline}))

    _, trends = repository_trends(runs)

    assert [(t.repository, t.now.results) for t in trends] == [("o/a", 1)]
    assert repository_trends([run(result("x", P), day=19)]) == (None, ())
