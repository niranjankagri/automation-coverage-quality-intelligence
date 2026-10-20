"""The producers file and the ingestion audit."""

from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qualityintel.collect.audit import audit, render_markdown, render_text
from qualityintel.collect.collector import ProducerOutcome
from qualityintel.collect.config import ProducersError, load_producers
from qualityintel.models.collection import PipelineCollection

pytestmark = pytest.mark.unit

REPO_FILE = Path(__file__).parents[3] / "config" / "producers.toml"
GOOD = """
[[producer]]
repository = "o/r"
workflow = "ci.yml"
context = { framework = "pytest" }
[[producer.job]]
name = "api"
artifact = "report-api"
path = "junit.xml"
context = { browser = "chromium" }
"""


def write(tmp_path: Path, text: str) -> Path:
    """A producers file."""
    path = tmp_path / "producers.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_the_repository_producers_file_is_valid() -> None:
    """The file CI uses: four repositories, every job with one path."""
    config = load_producers(REPO_FILE)

    assert {p.repository.split("/")[1] for p in config.producer} == {
        "enterprise-test-automation-framework",
        "python-pytest-framework",
        "cypress-typescript-framework",
        "robot-framework-automation",
    }
    assert all(job.path for p in config.producer for job in p.job)


def test_job_context_adds_to_the_producer_context(tmp_path: Path) -> None:
    """Framework from the producer, browser from the job."""
    producer = load_producers(write(tmp_path, GOOD)).producer[0]

    context = producer.job_context(producer.job[0])
    assert (context.framework, context.browser) == ("pytest", "chromium")
    assert producer.name == "r"


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (('path = "junit.xml"', 'path = "../junit.xml"'), "relative path inside the artifact"),
        (('path = "junit.xml"', 'path = "/etc/junit.xml"'), "relative path inside the artifact"),
        (('path = "junit.xml"', 'path = "C:/x.xml"'), "relative path inside the artifact"),
        (('repository = "o/r"', 'repository = "not a repo"'), "repository"),
        (('name = "api"', 'name = "a b"'), "name"),
        (('workflow = "ci.yml"', 'workflow = "ci.yml"\ntoken = "x"'), "Extra inputs are not permitted"),
    ],
)
def test_invalid_producers_are_refused_with_the_field(
    tmp_path: Path, change: tuple[str, str], message: str
) -> None:
    """A path cannot point outside the artifact; unknown keys (e.g. a token) are errors."""
    with pytest.raises(ProducersError, match=message):
        load_producers(write(tmp_path, GOOD.replace(*change)))


def test_duplicate_jobs_and_workflows_are_refused(tmp_path: Path) -> None:
    """A job name twice, or the same workflow twice, would collect a pipeline twice."""
    job = '[[producer.job]]\nname = "api"\nartifact = "x"\npath = "a.xml"\n'
    with pytest.raises(ProducersError, match="job names must be unique"):
        load_producers(write(tmp_path, GOOD + job))
    with pytest.raises(ProducersError, match="each repository workflow once"):
        load_producers(write(tmp_path, GOOD + GOOD))


def record(
    pid: str, state: str, conclusion: str, day: int, problems: tuple[str, ...] = ()
) -> PipelineCollection:
    """A stored collection record of repository o/r."""
    return PipelineCollection(
        pipeline_id=pid,
        attempt=1,
        repository="o/r",
        workflow="ci.yml",
        run_number=day,
        conclusion=conclusion,
        url=f"https://github.com/o/r/actions/runs/{day}",
        started_at=datetime(2026, 10, day, tzinfo=UTC),
        collected_at=datetime(2026, 10, 20, tzinfo=UTC),
        state=state,  # type: ignore[arg-type]
        runs=2,
        results=10,
        problems=problems,
    )


def test_audit_counts_per_repository_including_silent_ones() -> None:
    """Records in the period counted; a repository without runs and an API error are shown."""
    records = [
        record("r#1", "complete", "success", 19),
        record("r#2", "incomplete", "cancelled", 20, ("job ui: artifact report-ui not found",)),
        record("r#0", "complete", "success", 10),  # before the period
    ]
    outcomes = [ProducerOutcome("o/quiet", errors=["HTTP 403 (forbidden or rate limited)"])]

    rows = audit(records, ["o/r", "o/quiet"], datetime(2026, 10, 18, tzinfo=UTC), outcomes)

    first, quiet = rows
    assert (first.pipelines, first.complete, first.incomplete, first.results) == (2, 1, 1, 20)
    assert first.conclusions == Counter({"success": 1, "cancelled": 1})
    assert first.latest is not None
    assert first.latest.pipeline_id == "r#2"
    assert quiet.errors == ["HTTP 403 (forbidden or rate limited)"]
    text = render_text(rows, datetime(2026, 10, 18, tzinfo=UTC))
    assert "incomplete o/r: r#2 attempt 1: job ui: artifact report-ui not found" in text
    assert "ERROR o/quiet: HTTP 403" in text


def test_audit_markdown_escapes_what_comes_from_outside() -> None:
    """A problem text with Markdown in it is shown literally; the run link points to GitHub only."""
    bad = record("r#3", "incomplete", "failure", 20, ("job [x](https://evil.example): broken",))
    evil = bad.model_copy(update={"url": "javascript:alert(1)"})

    summary = render_markdown(
        audit([evil], ["o/r"], datetime(2026, 10, 18, tzinfo=UTC)), datetime(2026, 10, 18, tzinfo=UTC)
    )

    assert "\\[x\\]\\(https://evil.example\\)" in summary
    assert "javascript:" not in summary
