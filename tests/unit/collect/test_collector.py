"""Collection with a fake CI source serving zip files built from the real sample reports."""

import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qualityintel.collect.collector import collect
from qualityintel.collect.config import ProducersConfig
from qualityintel.collect.github import Artifact, CollectError, WorkflowRun
from qualityintel.history.store import HistoryStore

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[3] / "samples"
API_XML = SAMPLES / "results" / "pytest-notes-api" / "2026-10-19_fbb6ebe_39238240288.xml"
UI_XML = SAMPLES / "results" / "pytest-notes-ui-chromium" / "2026-10-19_fbb6ebe_39238240288.xml"
ALLURE = sorted((SAMPLES / "formats" / "allure-enterprise-api").iterdir())[-1]
SINCE = datetime(2026, 10, 18, tzinfo=UTC)
NOW = datetime(2026, 10, 20, 12, tzinfo=UTC)

CONFIG = ProducersConfig.model_validate(
    {
        "producer": [
            {
                "repository": "niranjankagri/python-pytest-framework",
                "workflow": "ci.yml",
                "context": {"framework": "pytest", "environment": "ci"},
                "job": [
                    {"name": "api", "artifact": "report-api", "path": "junit.xml"},
                    {
                        "name": "ui",
                        "artifact": "report-ui",
                        "path": "reports/junit.xml",
                        "context": {"browser": "chromium"},
                    },
                ],
            }
        ]
    }
)


def run(run_id: int = 100, attempt: int = 1, conclusion: str = "success") -> WorkflowRun:
    """A completed run of the pytest workflow."""
    return WorkflowRun(
        id=run_id,
        attempt=attempt,
        run_number=7,
        event="schedule",
        branch="main",
        commit="fbb6ebe12345",
        conclusion=conclusion,
        url=f"https://github.com/niranjankagri/python-pytest-framework/actions/runs/{run_id}",
        started_at=datetime(2026, 10, 19, 10, 33, tzinfo=UTC),
    )


class FakeSource:
    """Serves workflow runs and artifact zips from memory; can fail on purpose."""

    def __init__(self, runs: list[WorkflowRun], artifacts: dict[str, dict[str, bytes] | bytes]) -> None:
        self.runs = runs
        self.files = artifacts
        self.fail_download: CollectError | None = None
        self.fail_listing: CollectError | None = None
        self.downloads = 0

    def completed_runs(
        self, repository: str, workflow: str, branch: str, since: datetime
    ) -> list[WorkflowRun]:
        """The configured runs, or the listing failure."""
        if self.fail_listing:
            raise self.fail_listing
        return self.runs

    def artifacts(self, repository: str, run_id: int) -> list[Artifact]:
        """One artifact per configured name."""
        return [Artifact(id=i, name=name, size=1, expired=False) for i, name in enumerate(self.files)]

    def download(self, repository: str, artifact: Artifact, target: Path) -> Path:
        """Write the artifact as a zip (or the raw bytes given), or fail as configured."""
        if self.fail_download:
            raise self.fail_download
        self.downloads += 1
        content = self.files[artifact.name]
        if isinstance(content, bytes):
            target.write_bytes(content)
        else:
            with zipfile.ZipFile(target, "w") as bundle:
                for name, data in content.items():
                    bundle.writestr(name, data)
        return target


def good_artifacts() -> dict[str, dict[str, bytes] | bytes]:
    """Both jobs' artifacts with the real 19 Oct pytest reports, plus noise that is not read."""
    return {
        "report-api": {"junit.xml": API_XML.read_bytes(), "report.html": b"<html/>"},
        "report-ui": {"reports/junit.xml": UI_XML.read_bytes(), "reports/report.html": b"<html/>"},
    }


@pytest.fixture
def store(tmp_path: Path) -> HistoryStore:
    """An empty history database."""
    return HistoryStore(tmp_path / "h.db")


def test_a_complete_run_is_stored_as_one_pipeline_with_its_jobs(store: HistoryStore) -> None:
    """32 API + 14 UI results; pipeline id, attempt, branch, commit and per-job context kept."""
    with store:
        (outcome,) = collect(CONFIG, FakeSource([run()], good_artifacts()), store, SINCE, now=NOW)
        runs = store.runs()
        (record,) = store.collections()

    assert (outcome.seen, len(outcome.collected), outcome.errors) == (1, 1, [])
    assert (record.pipeline_id, record.state, record.conclusion, record.results) == (
        "python-pytest-framework#100",
        "complete",
        "success",
        46,
    )
    by_job = {r.pipeline.job: r for r in runs if r.pipeline}
    assert {job: len(r.results) for job, r in by_job.items()} == {"api": 32, "ui": 14}
    assert by_job["ui"].context.browser == "chromium"
    assert by_job["api"].context.framework == "pytest"
    assert by_job["api"].context.build == "fbb6ebe12345"  # the commit, like the samples
    assert by_job["api"].pipeline is not None
    assert (by_job["api"].pipeline.branch, by_job["api"].pipeline.commit, by_job["api"].pipeline.attempt) == (
        "main",
        "fbb6ebe12345",
        1,
    )
    assert by_job["api"].source == "api/junit.xml"


def test_collecting_again_adds_nothing_and_downloads_nothing(store: HistoryStore) -> None:
    """Idempotent: an attempt is collected once, whatever came of it."""
    source = FakeSource([run()], good_artifacts())
    with store:
        collect(CONFIG, source, store, SINCE, now=NOW)
        downloads, counts = source.downloads, store.count()
        (outcome,) = collect(CONFIG, source, store, SINCE, now=NOW)

        assert (outcome.already_collected, len(outcome.collected)) == (1, 0)
        assert source.downloads == downloads
        assert store.count() == counts


def test_a_rerun_attempt_is_a_new_collection(store: HistoryStore) -> None:
    """Attempt 2 of the same run is collected next to attempt 1."""
    with store:
        collect(CONFIG, FakeSource([run(attempt=1)], good_artifacts()), store, SINCE, now=NOW)
        rerun = good_artifacts()
        rerun["report-api"] = {"junit.xml": API_XML.read_bytes().replace(b'time="', b'time="1', 1)}
        collect(CONFIG, FakeSource([run(attempt=2)], rerun), store, SINCE, now=NOW)

        assert [(c.attempt, c.state) for c in store.collections()] == [(2, "complete"), (1, "complete")]


def test_a_cancelled_run_is_recorded_incomplete_with_the_missing_job(store: HistoryStore) -> None:
    """The UI job uploaded nothing: what exists is stored, the record says what is missing."""
    artifacts = good_artifacts()
    del artifacts["report-ui"]
    with store:
        collect(CONFIG, FakeSource([run(conclusion="cancelled")], artifacts), store, SINCE, now=NOW)
        (record,) = store.collections()
        stored_jobs = {r.pipeline.job for r in store.runs() if r.pipeline}

    assert (record.state, record.conclusion, record.runs) == ("incomplete", "cancelled", 1)
    assert record.problems == (
        "job ui: artifact report-ui not found (job not run, cancelled or failed early)",
    )
    assert stored_jobs == {"api"}


def test_a_failed_run_with_all_reports_is_complete_but_keeps_its_conclusion(store: HistoryStore) -> None:
    """Failure and cancellation stay distinguishable from completeness."""
    with store:
        collect(CONFIG, FakeSource([run(conclusion="failure")], good_artifacts()), store, SINCE, now=NOW)
        (record,) = store.collections()

    assert (record.state, record.conclusion) == ("complete", "failure")


def test_a_path_holding_two_formats_is_refused_instead_of_counted_twice(store: HistoryStore) -> None:
    """The enterprise layout: Allure results and Surefire XML of one execution in one artifact."""
    config = CONFIG.model_copy(
        update={
            "producer": (
                CONFIG.producer[0].model_copy(
                    update={"job": (CONFIG.producer[0].job[0].model_copy(update={"path": "."}),)}
                ),
            )
        }
    )
    allure = {f"allure-results/{p.name}": p.read_bytes() for p in ALLURE.iterdir()}
    artifacts: dict[str, dict[str, bytes] | bytes] = {
        "report-api": {**allure, "surefire-reports/TEST-TestSuite.xml": API_XML.read_bytes()}
    }
    with store:
        collect(config, FakeSource([run()], artifacts), store, SINCE, now=NOW)
        (record,) = store.collections()

    assert record.state == "incomplete"
    assert record.runs == 0
    assert "holds Allure and JUnit XML results" in record.problems[0]


def test_duplicate_report_contents_are_visible_and_make_the_collection_incomplete(
    store: HistoryStore,
) -> None:
    """Identical files are not silently discarded while the attempt is marked complete."""
    config = CONFIG.model_copy(
        update={
            "producer": (
                CONFIG.producer[0].model_copy(
                    update={"job": (CONFIG.producer[0].job[0].model_copy(update={"path": "."}),)}
                ),
            )
        }
    )
    artifacts: dict[str, dict[str, bytes] | bytes] = {
        "report-api": {"first.xml": API_XML.read_bytes(), "copy.xml": API_XML.read_bytes()}
    }

    with store:
        collect(config, FakeSource([run()], artifacts), store, SINCE, now=NOW)
        (record,) = store.collections()

    assert record.state == "incomplete"
    assert record.results == 32
    assert any("duplicate report" in problem and "copy.xml" in problem for problem in record.problems)


def test_duplicate_artifact_names_are_not_resolved_by_arbitrary_order(store: HistoryStore) -> None:
    """The correct artifact cannot be inferred when GitHub lists two with the configured name."""

    class DuplicateArtifacts(FakeSource):
        def artifacts(self, repository: str, run_id: int) -> list[Artifact]:
            return [
                *super().artifacts(repository, run_id),
                Artifact(id=999, name="report-api", size=1, expired=False),
            ]

    with store:
        collect(CONFIG, DuplicateArtifacts([run()], good_artifacts()), store, SINCE, now=NOW)
        (record,) = store.collections()

    assert record.state == "incomplete"
    assert any("job api: artifact report-api is ambiguous" in problem for problem in record.problems)


def test_a_zip_file_directory_collision_becomes_an_incomplete_attempt(store: HistoryStore) -> None:
    """A malformed artifact cannot crash the collector with NotADirectoryError."""
    artifacts = good_artifacts()
    artifacts["report-api"] = {"junit.xml": API_XML.read_bytes(), "junit.xml/nested.xml": b"<testsuite/>"}

    with store:
        collect(CONFIG, FakeSource([run()], artifacts), store, SINCE, now=NOW)
        (record,) = store.collections()

    assert record.state == "incomplete"
    assert any("conflicting file paths" in problem for problem in record.problems)


def test_a_wrong_path_and_a_broken_zip_are_named(store: HistoryStore) -> None:
    """Problems that belong to the run are recorded with the job they concern."""
    artifacts = good_artifacts()
    artifacts["report-api"] = {"other.xml": b"<testsuite/>"}
    artifacts["report-ui"] = b"<html>not a zip</html>"
    with store:
        collect(CONFIG, FakeSource([run()], artifacts), store, SINCE, now=NOW)
        (record,) = store.collections()

    assert record.problems[0] == "job api: junit.xml is not in artifact report-api"
    assert record.problems[1].startswith("job ui: ui.zip: not a readable zip file")


def test_a_transient_failure_records_nothing_so_the_run_is_tried_again(store: HistoryStore) -> None:
    """A missing token or a rate limit says nothing about the run."""
    source = FakeSource([run()], good_artifacts())
    source.fail_download = CollectError("HTTP 403 (forbidden or rate limited)", transient=True)
    with store:
        (first,) = collect(CONFIG, source, store, SINCE, now=NOW)
        assert store.collections() == []
        source.fail_download = None
        (second,) = collect(CONFIG, source, store, SINCE, now=NOW)

    assert first.errors == ["run 100: HTTP 403 (forbidden or rate limited)"]
    assert (len(second.collected), second.errors) == (1, [])


def test_a_producer_that_cannot_be_listed_does_not_stop_the_others(store: HistoryStore) -> None:
    """One error per producer; the next producer is still collected."""
    two = CONFIG.model_copy(
        update={
            "producer": (CONFIG.producer[0], CONFIG.producer[0].model_copy(update={"workflow": "other.yml"}))
        }
    )
    failing = FakeSource([run()], good_artifacts())
    failing.fail_listing = CollectError("HTTP 404 (not found or expired)")
    with store:
        outcomes = collect(two, failing, store, SINCE, now=NOW)

    assert [o.errors for o in outcomes] == [
        ["HTTP 404 (not found or expired)"],
        ["HTTP 404 (not found or expired)"],
    ]


def test_only_the_named_repositories_are_collected(store: HistoryStore) -> None:
    """--repository limits the pass (by full name or by repository name)."""
    with store:
        assert collect(CONFIG, FakeSource([run()], good_artifacts()), store, SINCE, ["other"], now=NOW) == []
        (outcome,) = collect(
            CONFIG, FakeSource([run()], good_artifacts()), store, SINCE, ["python-pytest-framework"], now=NOW
        )

    assert len(outcome.collected) == 1


def test_collected_runs_carry_their_repository(store: HistoryStore) -> None:
    """The repository comes from the producers file, not from names."""
    with store:
        collect(CONFIG, FakeSource([run()], good_artifacts()), store, SINCE, now=NOW)
        repositories = {r.pipeline.repository for r in store.runs() if r.pipeline}

    assert repositories == {"niranjankagri/python-pytest-framework"}


def test_runs_before_the_producers_since_are_neither_collected_nor_incomplete(store: HistoryStore) -> None:
    """A repository that started publishing results today: yesterday's runs are not missing data."""
    data = CONFIG.model_dump()
    data["producer"][0]["since"] = datetime(2026, 10, 19, 12, tzinfo=UTC)
    config = ProducersConfig.model_validate(data)
    before = run(run_id=100)  # started 10:33, before the contract
    after = WorkflowRun(
        **{**before.__dict__, "id": 101, "started_at": datetime(2026, 10, 19, 13, tzinfo=UTC)}
    )

    with store:
        (outcome,) = collect(config, FakeSource([before, after], good_artifacts()), store, SINCE, now=NOW)
        records = store.collections()

    assert outcome.seen == 1
    assert [r.pipeline_id for r in records] == ["python-pytest-framework#101"]


def test_since_must_carry_its_offset() -> None:
    """A date-time without an offset would be read in some time zone: refused."""
    data = CONFIG.model_dump()
    data["producer"][0]["since"] = "2026-10-19T12:00:00"

    with pytest.raises(ValueError, match="timezone"):
        ProducersConfig.model_validate(data)


def test_a_file_without_a_timestamp_takes_the_start_of_its_ci_run(store: HistoryStore) -> None:
    """Surefire, JUnit 5, k6 ... write no timestamp: the run must still sort and filter by date."""
    undated = b'<testsuite name="S" tests="1"><testcase classname="C" name="t"/></testsuite>'
    files: dict[str, dict[str, bytes] | bytes] = {
        "report-api": {"junit.xml": undated},
        "report-ui": {"reports/junit.xml": UI_XML.read_bytes()},
    }

    with store:
        collect(CONFIG, FakeSource([run()], files), store, SINCE, now=NOW)
        by_job = {r.pipeline.job: r for r in store.runs() if r.pipeline}

    assert by_job["api"].started_at == run().started_at  # the CI run's start
    assert by_job["ui"].started_at != run().started_at  # a file's own timestamp is kept


def test_an_expired_artifact_makes_the_run_incomplete_and_says_so(store: HistoryStore) -> None:
    """GitHub keeps artifacts 90 days: a run collected too late is incomplete, never complete."""

    class Expiring(FakeSource):
        def artifacts(self, repository: str, run_id: int) -> list[Artifact]:
            return [
                Artifact(id=i, name=name, size=1, expired=name == "report-ui")
                for i, name in enumerate(self.files)
            ]

    with store:
        collect(CONFIG, Expiring([run()], good_artifacts()), store, SINCE, now=NOW)
        (record,) = store.collections()

    assert record.state == "incomplete"
    assert "job ui: artifact report-ui has expired" in record.problems
