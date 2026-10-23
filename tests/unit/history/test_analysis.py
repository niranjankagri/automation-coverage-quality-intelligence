"""History rules on small hand-made histories (one test, one context unless stated)."""

import pytest

from qualityintel.history.analysis import (
    DEFAULTS,
    HistorySettings,
    Stability,
    classify,
    compare_runs,
    duration_regressions,
    failure_signature,
    recurring_failures,
    repeated_errors,
    slow_tests,
    stability_report,
    summary_by,
    timelines,
    trend,
)
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio
from qualityintel.models.results import TestRun

from ..traceability.helpers import result, run

pytestmark = pytest.mark.unit

P, F, E, S = Outcome.PASSED, Outcome.FAILED, Outcome.ERROR, Outcome.SKIPPED


def history(
    *outcomes: Outcome, builds: str = "", browser: str = "firefox", failure: dict[str, str] | None = None
) -> list[TestRun]:
    """One run per outcome on consecutive days; ``builds`` gives one build letter per run."""
    letters = builds or "".join(chr(ord("a") + i) for i in range(len(outcomes)))
    return [
        run(result("t", outcome, failure=failure), day=day, build=letters[i], browser=browser)
        for i, (day, outcome) in enumerate(zip(range(1, 30), outcomes, strict=False))
    ]


def status(runs: list[TestRun], settings: HistorySettings = DEFAULTS) -> Stability:
    """Classification of the single test in these runs."""
    (line,) = timelines(runs).values()
    return classify(line, settings).status


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ([P, P, P, P], Stability.STABLE),
        ([P, P], Stability.INSUFFICIENT_DATA),
        ([P, P, F, F], Stability.CONSISTENTLY_FAILING),
        ([P, P, P, F], Stability.NEW_FAILURE),
        ([P, F, P, P], Stability.RECOVERED),  # 2 flips on different builds: not flaky (3 needed here)
        ([P, F, P, F, P], Stability.FLAKY_CANDIDATE),  # 4 flips
        ([P, E, E], Stability.CONSISTENTLY_FAILING),  # errors count as failures
        ([P, S, S, P, P], Stability.STABLE),  # skips are ignored
        ([S, S, S], Stability.INSUFFICIENT_DATA),
    ],
    ids=[
        "stable",
        "too-few",
        "two-failures-in-a-row",
        "new",
        "recovered",
        "many-flips",
        "errors",
        "skips",
        "only-skips",
    ],
)
def test_classification_rules(outcomes: list[Outcome], expected: Stability) -> None:
    """Each rule of docs/metrics.md on a minimal history (every run a different build)."""
    settings = HistorySettings(flips_for_flaky=3)

    assert status(history(*outcomes), settings) == expected


def test_same_build_passing_and_failing_is_a_flaky_candidate() -> None:
    """No code change between a pass and a fail: the strongest flaky signal."""
    runs = history(P, P, F, P, builds="aabb")

    (line,) = timelines(runs).values()
    verdict = classify(line)

    assert verdict.status is Stability.FLAKY_CANDIDATE
    assert verdict.mixed_builds == ("b",)
    assert "passed and failed on the same build (b)" in verdict.reasons


def test_pass_after_retry_is_a_flaky_candidate_even_with_little_history() -> None:
    """A Surefire flakyFailure in a single run is already evidence."""
    runs = [run(result("t", P, retries=1), day=1, build="a")]

    assert status(runs) is Stability.FLAKY_CANDIDATE


def test_consistent_failure_wins_over_flaky_signals() -> None:
    """Two failures in a row on a new build are a confirmed failure, even after flips."""
    runs = history(P, F, P, F, F, builds="aaabb")

    assert status(runs) is Stability.CONSISTENTLY_FAILING


def test_window_limits_how_far_back_history_counts() -> None:
    """An old failure outside the window no longer makes the test 'recovered'."""
    runs = history(F, P, P, P, P)

    assert status(runs, HistorySettings(window=3)) is Stability.STABLE
    assert status(runs, HistorySettings(window=5)) is Stability.RECOVERED


def test_contexts_are_never_mixed() -> None:
    """Chrome failing and Firefox passing are two separate, stable/failing histories."""
    runs = history(P, P, P) + history(F, F, F, browser="chrome")

    rows = {r.context[2]: r.status for r in stability_report(runs)}

    assert rows == {"firefox": Stability.STABLE, "chrome": Stability.CONSISTENTLY_FAILING}


def test_report_lists_the_most_worrying_first() -> None:
    """Consistently failing, new failure, flaky, recovered ... stable last."""
    runs = [
        run(result("stable"), result("new"), result("broken", F), day=1, build="a"),
        run(result("stable"), result("new"), result("broken", F), day=2, build="b"),
        run(result("stable"), result("new", F), result("broken", F), day=3, build="c"),
    ]

    order = [(r.key, r.status) for r in stability_report(runs)]

    assert order == [
        ("suite::broken", Stability.CONSISTENTLY_FAILING),
        ("suite::new", Stability.NEW_FAILURE),
        ("suite::stable", Stability.STABLE),
    ]


def test_failure_rate_and_evidence_are_reported() -> None:
    """The row carries the numbers behind its classification."""
    (line,) = timelines(history(P, F, P, P, failure={"message": "boom"})).values()
    row = classify(line)

    assert row.failure_rate == Ratio(numerator=1, denominator=4)
    assert row.flips == 2


def test_classify_needs_an_execution() -> None:
    """An empty history is a programming error, not a stable test."""
    with pytest.raises(ValueError, match="at least one execution"):
        classify([])


@pytest.mark.parametrize(
    ("message", "signature"),
    [
        ("Timeout 15000ms exceeded.", "TimeoutError: Timeout <n>ms exceeded."),
        ("Timeout 30000ms exceeded.\nCall log: ...", "TimeoutError: Timeout <n>ms exceeded."),
        ("Session ff4a5eb5-ea51-4f5a-98a2-c39eb275c8d3 died", "TimeoutError: Session <uuid> died"),
        ("object at 0x7f3a9c", "TimeoutError: object at <hex>"),
    ],
)
def test_failure_signature_masks_volatile_parts(message: str, signature: str) -> None:
    """Numbers, ids and addresses change between runs; the cause does not."""
    failed = result("t", F, failure={"message": message, "type": "TimeoutError"})

    assert failure_signature(failed) == signature


def test_failure_signature_without_details_is_the_outcome() -> None:
    """An <error/> with no message still has a stable signature."""
    assert failure_signature(result("t", E)) == "error"


def test_recurring_failures_need_several_runs() -> None:
    """The same cause in two runs is recurring; twice in one run is not."""
    timeout = {"message": "Timeout 15000ms exceeded.", "type": "TimeoutError"}
    runs = [
        run(result("a", F, failure=timeout), result("b", F, failure=timeout), day=1),
        run(result("c", F, failure={"message": "Timeout 30000ms exceeded.", "type": "TimeoutError"}), day=2),
        run(result("d", F, failure={"message": "only once", "type": "X"}), day=3),
    ]

    (found,) = recurring_failures(runs)

    assert found.signature == "TimeoutError: Timeout <n>ms exceeded."
    assert (found.runs, found.occurrences) == (2, 3)
    assert found.tests == ("suite::a", "suite::b", "suite::c")


def failing_on(signature: str, *days: int) -> list[TestRun]:
    """One run per day in which test ``signature`` fails with the message ``signature``."""
    return [run(result(signature, F, failure={"message": signature, "type": "X"}), day=d) for d in days]


def test_a_cause_failing_this_week_outranks_an_older_more_frequent_one() -> None:
    """Rank: runs in the 7 days before the newest run first, then all runs (docs/metrics.md)."""
    runs = [*failing_on("old", 1, 2, 3), *failing_on("new", 25, 28)]

    ranked = recurring_failures(runs)

    assert [(f.signature, f.recent_runs, f.runs) for f in ranked] == [("X: new", 2, 2), ("X: old", 0, 3)]


def test_equal_recent_runs_rank_by_total_runs_then_latest_occurrence() -> None:
    """Ties on recent runs go to the cause seen in more runs, then to the one seen last."""
    runs = [*failing_on("a", 20, 27), *failing_on("b", 10, 21, 26), *failing_on("c", 22, 28)]

    ranked = recurring_failures(runs)

    # since = 28 Oct - 7 days = 21 Oct: a 1 recent (27), b 2 (21, 26), c 2 (22, 28)
    assert [(f.signature, f.recent_runs, f.runs) for f in ranked] == [
        ("X: b", 2, 3),
        ("X: c", 2, 2),
        ("X: a", 1, 2),
    ]


def test_recent_is_measured_from_the_newest_run_not_the_clock() -> None:
    """The same history ranks the same on any day: the window ends at its newest run."""
    (found,) = recurring_failures(failing_on("t", 1, 3))

    assert found.recent_runs == 2


def test_recurring_failure_lists_its_runs_newest_first() -> None:
    """Every supporting run is linked; undated runs come last and never count as recent."""
    dated = failing_on("t", 2, 5)
    undated = run(result("t", F, failure={"message": "t", "type": "X"}), day=None)

    (found,) = recurring_failures([*dated, undated])

    assert found.run_ids == (dated[1].run_id, dated[0].run_id, undated.run_id)
    assert found.recent_runs == 2


def test_repeated_errors_count_runs_not_rows() -> None:
    """Errors (not assertion failures) in two different runs."""
    runs = [run(result("a", E), result("b", F), day=1), run(result("a", E), result("b", F), day=2)]

    assert repeated_errors(runs) == {"suite::a": 2}


def test_duration_regression_needs_two_slow_runs_in_a_row() -> None:
    """One slow run is noise; two in a row against a baseline of 1 s are a regression."""

    def timed(*seconds: float) -> list[TestRun]:
        return [run(result("t", duration_seconds=s), day=i + 1) for i, s in enumerate(seconds)]

    assert duration_regressions(timed(1, 1, 1, 1, 5)) == []
    (found,) = duration_regressions(timed(1, 1, 1, 4, 5))
    assert (found.baseline_seconds, found.latest_seconds, found.baseline_runs) == (1, 5, 3)
    assert found.increase == 4


def test_small_absolute_changes_are_not_regressions() -> None:
    """0.01 s -> 0.05 s is 400 % but below the 1 s floor."""
    runs = [
        run(result("t", duration_seconds=s), day=i + 1) for i, s in enumerate([0.01, 0.01, 0.01, 0.05, 0.05])
    ]

    assert duration_regressions(runs) == []


def test_slow_tests_use_the_median() -> None:
    """One very slow run does not make a fast test 'slow'."""
    runs = [
        run(result("fast", duration_seconds=s), result("slow", duration_seconds=3.0), day=i + 1)
        for i, s in enumerate([1.0, 1.0, 90.0])
    ]

    top = slow_tests(runs, top=1)

    assert [(t.key, t.median_seconds) for t in top] == [("suite::slow", 3.0)]


def test_trend_has_one_point_per_run_per_context() -> None:
    """Pass rate, failures and total time per run, oldest first."""
    runs = [
        run(result("a", duration_seconds=1.0), result("b", F, duration_seconds=2.0), day=2),
        run(result("a"), day=1),
    ]

    (points,) = trend(runs).values()

    assert [p.pass_rate for p in points] == [
        Ratio(numerator=1, denominator=1),
        Ratio(numerator=1, denominator=2),
    ]
    assert [p.failed for p in points] == [0, 1]
    assert points[1].total_seconds == 3.0


def test_compare_runs_lists_every_kind_of_change() -> None:
    """Newly failing, fixed, still failing, added, removed and clearly slower tests."""
    base = run(
        result("fixed", F),
        result("broken"),
        result("still", E),
        result("gone"),
        result("slow", duration_seconds=1.0),
        day=1,
    )
    head = run(
        result("fixed"),
        result("broken", F),
        result("still", F),
        result("new"),
        result("slow", duration_seconds=4.0),
        day=2,
    )

    diff = compare_runs(base, head)

    assert diff.newly_failing == ["suite::broken"]
    assert diff.fixed == ["suite::fixed"]
    assert diff.still_failing == ["suite::still"]
    assert diff.added == ["suite::new"]
    assert diff.removed == ["suite::gone"]
    assert diff.slower == [("suite::slow", 1.0, 4.0)]


def test_summary_by_pools_results_per_value() -> None:
    """Per build: number of runs and the pass rate of all their results together."""
    runs = [
        run(result("a"), result("b", F), day=1, build="1.0"),
        run(result("a"), result("b"), day=2, build="1.1"),
        run(result("a"), result("b"), day=3, build="1.1"),
        run(result("a"), day=4),
    ]

    by_build = summary_by(runs, "build")

    assert by_build == {
        "1.0": (1, Ratio(numerator=1, denominator=2)),
        "1.1": (2, Ratio(numerator=4, denominator=4)),
        "unspecified": (1, Ratio(numerator=1, denominator=1)),
    }
