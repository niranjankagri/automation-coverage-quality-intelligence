"""Build comparison: comparable suites only, changes from compare_runs, newly flaky, coverage."""

from datetime import UTC, datetime

import pytest

from qualityintel.history.builds import builds_in_order, compare_builds
from qualityintel.history.trends import CoverageSnapshot
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio
from qualityintel.models.results import TestRun

from ..traceability.helpers import result, run

pytestmark = pytest.mark.unit

F, P = Outcome.FAILED, Outcome.PASSED


def runs_of(
    build: str, day: int, outcomes: dict[str, Outcome], browser: str = "chrome", durations: float = 1.0
) -> TestRun:
    """One run of build ``build`` on 2026-10-<day> in a browser."""
    return run(
        *(result(k, o, duration_seconds=durations) for k, o in outcomes.items()),
        day=day,
        build=build,
        browser=browser,
    )


def test_changes_are_found_where_the_same_suite_ran_in_both_builds() -> None:
    """Newly failing, recovered, still failing, added and removed tests, per comparable context."""
    base = runs_of("b1", 18, {"a": P, "b": F, "c": F, "gone": P})
    head = runs_of("b2", 19, {"a": F, "b": P, "c": F, "new": P})
    only_base = runs_of("b1", 18, {"x": P}, browser="firefox")

    comparison = compare_builds([base, head, only_base], "b1", "b2")

    (pair,) = comparison.compared
    assert pair.changes.newly_failing == ["suite::a"]
    assert pair.changes.fixed == ["suite::b"]
    assert pair.changes.still_failing == ["suite::c"]
    assert pair.changes.added == ["suite::new"]
    assert pair.changes.removed == ["suite::gone"]
    assert comparison.only_in_base == ("-/-/firefox/-",)
    assert comparison.only_in_head == ()
    assert comparison.base.pass_rate == Ratio(numerator=3, denominator=5)  # chrome 2 of 4 + firefox 1 of 1


def test_builds_without_a_common_suite_are_not_comparable() -> None:
    """Different browsers only: nothing is compared, both sides listed."""
    comparison = compare_builds(
        [runs_of("b1", 18, {"a": P}), runs_of("b2", 19, {"a": F}, browser="firefox")],
        "b1",
        "b2",
    )

    assert not comparison.comparable
    assert comparison.only_in_base == ("-/-/chrome/-",)
    assert comparison.only_in_head == ("-/-/firefox/-",)


def test_slower_tests_use_the_documented_thresholds() -> None:
    """50 % and 0.5 s slower (HistorySettings defaults): 1 s -> 2 s is slower, 1 s -> 1.2 s is not."""
    slow = compare_builds(
        [runs_of("b1", 18, {"a": P}, durations=1.0), runs_of("b2", 19, {"a": P}, durations=2.0)],
        "b1",
        "b2",
    )
    fine = compare_builds(
        [runs_of("b1", 18, {"a": P}, durations=1.0), runs_of("b2", 19, {"a": P}, durations=1.2)],
        "b1",
        "b2",
    )

    assert slow.compared[0].changes.slower == [("suite::a", 1.0, 2.0)]
    assert fine.compared[0].changes.slower == []


def test_a_test_that_became_a_flaky_candidate_is_named() -> None:
    """Pass and fail on the same head build: a flaky candidate up to head, not up to base."""
    history = [
        runs_of("b1", 17, {"a": P}),
        runs_of("b1", 18, {"a": P}),
        runs_of("b2", 19, {"a": F}),
        run(result("a", P), day=19, hour=11, build="b2", browser="chrome"),
    ]

    comparison = compare_builds(history, "b1", "b2")

    assert comparison.newly_flaky == (("suite::a", "-/-/chrome/-"),)


def test_coverage_comes_from_the_latest_snapshot_before_each_build() -> None:
    """No snapshot before the base build: None, not a guess."""
    snapshot = CoverageSnapshot(
        taken_at=datetime(2026, 10, 18, 12, tzinfo=UTC),
        catalog="catalog.toml",
        catalog_sha256="0" * 64,
        requirements=10,
        requirement_coverage=Ratio(numerator=8, denominator=10),
        automation_coverage=Ratio(numerator=5, denominator=6),
        automated_requirement_coverage=Ratio(numerator=4, denominator=10),
    )
    comparison = compare_builds(
        [runs_of("b1", 18, {"a": P}), runs_of("b2", 19, {"a": P})], "b1", "b2", [snapshot]
    )

    assert comparison.base.coverage is None  # the base build ran at 09:00, the snapshot is from 12:00
    assert comparison.head.coverage == snapshot


def test_an_unknown_build_is_a_key_error_and_builds_are_ordered_by_time() -> None:
    """The order of the build selectors is the order in which builds first ran."""
    history = [
        runs_of("late", 19, {"a": P}),
        runs_of("early", 17, {"a": P}),
        run(result("a"), day=None, build="undated"),
    ]

    with pytest.raises(KeyError):
        compare_builds(history, "early", "missing")
    assert builds_in_order(history) == ["early", "late", "undated"]
