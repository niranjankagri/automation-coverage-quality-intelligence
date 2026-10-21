import pytest

from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio
from qualityintel.models.results import PipelineJob, TestRun
from qualityintel.traceability.report import (
    FAILING,
    NOT_AUTOMATED,
    NOT_RUN,
    PASSING,
    SKIPPED,
    RunFilters,
    build_report,
    latest_runs,
)

from .helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit


def test_latest_run_per_context_replaces_older_runs() -> None:
    """Same context: the newer run wins. Different browser: a separate context."""
    old_firefox = run(result("a"), day=18, browser="firefox")
    new_firefox = run(result("a"), day=19, browser="firefox")
    chrome = run(result("a"), day=17, browser="chrome")

    assert latest_runs([new_firefox, old_firefox, chrome]) == (chrome, new_firefox)


def test_build_is_not_part_of_the_context() -> None:
    """A new build of the same job replaces the old one in the snapshot."""
    first = run(result("a"), day=18, build="b1", framework="pytest")
    second = run(result("a"), day=19, build="b2", framework="pytest")

    assert latest_runs([first, second]) == (second,)


def test_dated_run_beats_undated_run() -> None:
    """A run without a timestamp never hides a dated one; among undated, the last given wins."""
    undated_a = run(result("a"), day=None, source="a.xml")
    undated_b = run(result("b"), day=None, source="b.xml")
    dated = run(result("c"), day=1)

    assert latest_runs([undated_a, undated_b]) == (undated_b,)
    assert latest_runs([dated, undated_a]) == (dated,)


@pytest.mark.parametrize(
    ("outcomes", "expected"),
    [
        ([Outcome.PASSED, Outcome.PASSED], PASSING),
        ([Outcome.PASSED, Outcome.FAILED], FAILING),
        ([Outcome.PASSED, Outcome.ERROR], FAILING),
        ([Outcome.PASSED, Outcome.SKIPPED], PASSING),
        ([Outcome.SKIPPED, Outcome.SKIPPED], SKIPPED),
        ([], NOT_RUN),
    ],
)
def test_case_status_from_its_executions(outcomes: list[Outcome], expected: str) -> None:
    """Any failure or error fails the case; skips alone are 'skipped'; nothing is 'not run'."""
    cat = catalog([req("R1")], [case("TC-1", "R1")])
    results = [result(f"TC-1 {i}", outcome) for i, outcome in enumerate(outcomes)]

    report = build_report(cat, [run(*results)] if results else [])

    assert report.cases["TC-1"].status == expected


def test_requirement_takes_the_worst_status_of_its_automated_cases() -> None:
    """R1: pass + fail = failing. R2: pass + not run = not run. R3: manual only = not automated."""
    cat = catalog(
        [req("R1"), req("R2"), req("R3")],
        [
            case("A", "R1"),
            case("B", "R1"),
            case("C", "R2"),
            case("D", "R2"),
            case("E", "R3", status="manual"),
        ],
    )

    report = build_report(cat, [run(result("A"), result("B", Outcome.FAILED), result("C"))])

    assert report.requirement_status == {"R1": FAILING, "R2": NOT_RUN, "R3": NOT_AUTOMATED}


def test_failing_critical_requirements_are_listed() -> None:
    """Only critical requirements with failing automated tests."""
    cat = catalog(
        [req("R1", criticality="critical"), req("R2", criticality="high"), req("R3", criticality="critical")],
        [case("A", "R1"), case("B", "R2"), case("C", "R3")],
    )

    report = build_report(cat, [run(result("A", Outcome.FAILED), result("B", Outcome.FAILED), result("C"))])

    assert report.failing_critical == ("R1",)


def test_pass_rate_and_counts_cover_the_whole_snapshot() -> None:
    """Unmatched results count too: pass rate is about what ran, not about the catalog."""
    cat = catalog([req("R1")], [case("A", "R1")])
    old = run(result("A", Outcome.FAILED), day=18)
    new = run(result("A"), result("other", Outcome.FAILED), result("skip", Outcome.SKIPPED), day=19)

    report = build_report(cat, [old, new])

    assert report.snapshot == (new,)
    assert report.pass_rate == Ratio(numerator=1, denominator=2)
    assert report.outcome_counts[Outcome.SKIPPED] == 1
    assert [e.result.name for e in report.unmatched] == ["other", "skip"]
    assert report.cases["A"].status == PASSING  # the old failure is history, not the snapshot


def test_run_filters_choose_the_runs() -> None:
    """Only firefox runs: the chrome failure does not count."""
    cat = catalog([req("R1")], [case("A", "R1")])
    runs = [run(result("A"), browser="firefox"), run(result("A", Outcome.FAILED), browser="chrome")]

    report = build_report(cat, runs, run_filters=RunFilters(browsers=frozenset({"firefox"})))

    assert report.requirement_status["R1"] == PASSING
    assert [r.context.browser for r in report.snapshot] == ["firefox"]


def test_automated_cases_without_results_and_unknown_ids() -> None:
    """Cases nothing ran for, and explicit ids not in the catalog, are reported."""
    cat = catalog([req("R1")], [case("A", "R1"), case("B", "R1")])

    report = build_report(cat, [run(result("A x", test_ids=("ZZ-1",)))])

    assert report.automated_cases_without_results == ("B",)
    assert report.unknown_ids == {"ZZ-1": 1}


def test_empty_input_gives_not_applicable_pass_rate() -> None:
    """No runs at all: pass rate n/a, every automated case 'not run'."""
    report = build_report(catalog([req("R1")], [case("A", "R1")]), [])

    assert report.pass_rate.value is None
    assert report.requirement_status == {"R1": NOT_RUN}


def test_two_pipeline_jobs_in_the_same_context_are_both_in_the_snapshot() -> None:
    """Component and UI jobs both run in Chrome: different suites, neither replaces the other."""
    component = run(result("C"), hour=9, browser="chrome").model_copy(
        update={"pipeline": PipelineJob(pipeline_id="1", job="component")}
    )
    ui = run(result("U"), hour=10, browser="chrome").model_copy(
        update={"pipeline": PipelineJob(pipeline_id="1", job="ui")}
    )
    next_night_ui = run(result("U"), day=20, browser="chrome").model_copy(
        update={"pipeline": PipelineJob(pipeline_id="2", job="ui")}
    )

    assert latest_runs([component, ui]) == (component, ui)
    assert latest_runs([component, ui, next_night_ui]) == (component, next_night_ui)


def test_one_execution_counts_every_run() -> None:
    """Several files of one job in one context are one execution, not competing runs."""
    first = run(result("A"), hour=9, source="TEST-A.xml")
    second = run(result("B"), hour=10, source="TEST-B.xml")
    cat = catalog([req("R1")], [case("TC", "R1", automated_by=("suite::*",))])

    assert build_report(cat, [first, second]).snapshot == (second,)
    assert build_report(cat, [first, second], one_execution=True).snapshot == (first, second)


def test_runs_can_be_chosen_by_repository() -> None:
    """The repository comes from the pipeline job; runs without one never match a chosen repository."""
    pytest_run = run(result("A"), hour=9).model_copy(
        update={"pipeline": PipelineJob(pipeline_id="p#1", job="api", repository="o/pytest")}
    )
    cypress_run = run(result("B"), hour=10).model_copy(
        update={"pipeline": PipelineJob(pipeline_id="c#1", job="api", repository="o/cypress")}
    )
    plain = run(result("C"), hour=11)
    chosen = RunFilters(repositories=frozenset({"o/pytest"}))

    assert [r.run_id for r in (pytest_run, cypress_run, plain) if chosen.keeps(r)] == [pytest_run.run_id]
    assert all(RunFilters().keeps(r) for r in (pytest_run, cypress_run, plain))


def _job(r: TestRun, pipeline: str, job: str, repository: str, attempt: int = 1) -> TestRun:
    """The run as part of a collected pipeline job."""
    return r.model_copy(
        update={
            "pipeline": PipelineJob(pipeline_id=pipeline, job=job, attempt=attempt, repository=repository)
        }
    )


def test_same_job_name_and_context_in_two_repositories_are_two_suites() -> None:
    """Two TestNG ``unit`` jobs on Linux (llm-feature-testing, ai-assisted, 2026-10-21): both count."""
    llm = _job(run(result("L"), hour=9), "llm#1", "unit", "o/llm-feature-testing")
    ai = _job(run(result("A"), hour=10), "ai#1", "unit", "o/ai-assisted-test-automation")

    assert latest_runs([llm, ai]) == (llm, ai)


def test_a_job_with_one_file_per_class_counts_all_files_of_its_latest_attempt() -> None:
    """Five Surefire files of one job are one suite; a newer attempt replaces all of them."""
    old = [_job(run(result(c), hour=9, source=f"it/TEST-{c}.xml"), "it#1", "it", "o/it") for c in "ABCDE"]
    new = [_job(run(result(c), day=20, source=f"it/TEST-{c}.xml"), "it#2", "it", "o/it") for c in "ABCD"]

    assert set(latest_runs(old)) == set(old)
    assert set(latest_runs([*old, *new])) == set(new)
