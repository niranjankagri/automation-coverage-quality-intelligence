import pytest

from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob, TestRun
from qualityintel.traceability.pipelines import PipelineState, pipeline_execution, pipeline_ids

from .helpers import result, run

pytestmark = pytest.mark.unit

JOBS = ("api", "ui-chrome", "ui-firefox")


def job_run(job: str, *outcomes: Outcome, attempt: int = 1, pipeline: str = "100", **meta: str) -> TestRun:
    """A run of one job of a pipeline, with one result per outcome."""
    results = [result(f"{job}-{i}", outcome) for i, outcome in enumerate(outcomes or (Outcome.PASSED,))]
    plain = run(*results, source=f"{job}-{attempt}.xml", hour=attempt)
    return plain.model_copy(
        update={"pipeline": PipelineJob(pipeline_id=pipeline, job=job, attempt=attempt, **meta)}
    )


def test_every_expected_job_reported_means_complete() -> None:
    """All three jobs, same commit: complete; the runs are the jobs' runs."""
    runs = [job_run(j, commit="abc", branch="main") for j in JOBS]

    execution = pipeline_execution(runs, "100", JOBS)

    assert execution.state is PipelineState.COMPLETE
    assert execution.problems == ()
    assert [j.name for j in execution.jobs] == list(JOBS)
    assert (execution.branch, execution.commit) == ("main", "abc")
    assert len(execution.runs) == 3


def test_a_failed_test_does_not_make_a_pipeline_incomplete() -> None:
    """Failures are for the gate's rules to judge; the pipeline itself reported fully."""
    runs = [job_run("api", Outcome.PASSED, Outcome.FAILED), job_run("ui-chrome"), job_run("ui-firefox")]

    execution = pipeline_execution(runs, "100", JOBS)

    assert execution.state is PipelineState.COMPLETE
    assert execution.jobs[0].outcome_counts[Outcome.FAILED] == 1


def test_an_interrupted_pipeline_is_incomplete_and_names_the_missing_job() -> None:
    """The Firefox job was cancelled: no runs from it."""
    execution = pipeline_execution([job_run("api"), job_run("ui-chrome")], "100", JOBS)

    assert execution.state is PipelineState.INCOMPLETE
    assert execution.missing == ("ui-firefox",)
    assert execution.problems == (
        "pipeline 100: job ui-firefox reported no results (not run, cancelled or interrupted)",
    )


def test_a_job_without_test_results_is_incomplete() -> None:
    """A job that crashed before its tests wrote an empty report."""
    empty = run(source="ui-firefox.xml").model_copy(
        update={"pipeline": PipelineJob(pipeline_id="100", job="ui-firefox")}
    )

    execution = pipeline_execution([job_run("api"), job_run("ui-chrome"), empty], "100", JOBS)

    assert execution.problems == ("pipeline 100: job ui-firefox reported runs without any test result",)


def test_jobs_that_tested_different_commits_are_not_one_pipeline() -> None:
    """Mixed artifacts (two pipelines' files under one id) are caught by the commit."""
    runs = [
        job_run("api", commit="abc"),
        job_run("ui-chrome", commit="abc"),
        job_run("ui-firefox", commit="def"),
    ]

    execution = pipeline_execution(runs, "100", JOBS)

    assert execution.state is PipelineState.INCOMPLETE
    assert execution.commit is None
    assert execution.problems == (
        "pipeline 100: jobs disagree on the commit: abc (api, ui-chrome), def (ui-firefox)",
    )


def test_a_rerun_job_replaces_its_first_attempt() -> None:
    """Attempt 1 failed, attempt 2 passed: only attempt 2 counts; attempt 1 is kept as superseded."""
    runs = [
        job_run("api"),
        job_run("ui-chrome", Outcome.FAILED, attempt=1),
        job_run("ui-chrome", Outcome.PASSED, attempt=2),
        job_run("ui-firefox"),
    ]

    execution = pipeline_execution(runs, "100", JOBS)
    chrome = execution.jobs[1]

    assert chrome.attempt == 2
    assert chrome.outcome_counts[Outcome.FAILED] == 0
    assert len(chrome.superseded) == 1
    assert len(execution.runs) == 3


def test_other_pipelines_and_plain_runs_are_ignored_and_extra_jobs_are_listed() -> None:
    """Only runs of the requested id count; an unexpected job is shown, not required."""
    runs = [*(job_run(j) for j in JOBS), job_run("docs"), job_run("api", pipeline="200"), run(result("x"))]

    execution = pipeline_execution(runs, "100", JOBS)

    assert execution.state is PipelineState.COMPLETE
    assert [(j.name, j.expected) for j in execution.jobs] == [
        ("api", True),
        ("ui-chrome", True),
        ("ui-firefox", True),
        ("docs", False),
    ]
    assert pipeline_ids(runs) == ["100", "200"]


def test_without_expected_jobs_the_jobs_found_are_the_pipeline() -> None:
    """History views know no job list: only consistency is checked."""
    assert pipeline_execution([job_run("api")], "100").state is PipelineState.COMPLETE
    assert pipeline_execution([], "100").problems == ("pipeline 100: no runs of this pipeline were read",)
