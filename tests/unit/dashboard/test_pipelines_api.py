"""``/api/pipelines`` and pipeline fields of ``/api/runs`` on the two real TaskBoard pipelines."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qualityintel.dashboard.app import create_app
from qualityintel.ingest.batch import import_pipeline
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.models.results import TestRun
from qualityintel.workspace import Workspace

pytestmark = pytest.mark.unit

PIPELINES = Path(__file__).parents[3] / "samples" / "pipelines" / "cypress-taskboard"
ALL_JOBS = "api,ui-chrome,ui-firefox,ui-edge,component"


def pipeline_runs() -> list[TestRun]:
    """Both sample pipelines imported as `qi history import --pipeline ... --job ...` would."""
    runs: list[TestRun] = []
    for folder in sorted(p for p in PIPELINES.iterdir() if p.is_dir()):
        _, commit, run_id = folder.name.split("_")
        jobs = {report.stem: [str(report)] for report in folder.glob("*.json")}
        batch = import_pipeline(
            jobs, run_id, commit=commit, repository="niranjankagri/cypress-typescript-framework"
        )
        assert batch.complete
        runs += batch.runs
    return runs


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The TaskBoard catalog with both pipelines."""
    return TestClient(create_app(Workspace(load_catalog(PIPELINES / "catalog.toml"), pipeline_runs())))


def test_pipelines_are_listed_newest_first_with_their_jobs(client: TestClient) -> None:
    """Without expected jobs both are consistent; the note says what that does not cover."""
    body = client.get("/api/pipelines").json()

    assert [p["pipeline_id"] for p in body["pipelines"]] == ["39238241112", "38842296207"]
    assert [p["state"] for p in body["pipelines"]] == ["complete", "complete"]
    assert [len(p["jobs"]) for p in body["pipelines"]] == [5, 4]
    assert body["pipelines"][0]["pass_rate"]["text"] == "100.0 % (147/147)"
    assert body["pipelines"][0]["commit"] == "80e331e"
    assert "No expected jobs given" in body["notes"][0]


def test_expected_jobs_reveal_the_cancelled_pipeline(client: TestClient) -> None:
    """With the five jobs the cancelled run is incomplete and names the Firefox job."""
    body = client.get("/api/pipelines", params={"jobs": ALL_JOBS}).json()
    complete, cancelled = body["pipelines"]

    assert complete["state"] == "complete"
    assert cancelled["state"] == "incomplete"
    assert cancelled["missing"] == ["ui-firefox"]
    assert body["expected_jobs"] == ALL_JOBS.split(",")
    assert body["notes"] == []


def test_a_run_filter_chooses_pipelines_but_keeps_them_whole(client: TestClient) -> None:
    """browser=firefox lists only the run that had a Firefox job, with all five of its jobs."""
    body = client.get("/api/pipelines", params={"browser": "firefox", "jobs": ALL_JOBS}).json()

    (only,) = body["pipelines"]
    assert only["pipeline_id"] == "39238241112"
    assert len(only["jobs"]) == 5
    assert only["state"] == "complete"


def test_requirement_matrix_repository_rows_count_only_observed_evidence(client: TestClient) -> None:
    """Repository denominators are linked requirements with matched results in that repository."""
    matrix = client.get("/api/requirements/matrix").json()
    (repository,) = matrix["by_repository"]
    rows = client.get(
        "/api/requirements", params={"repository": repository["repository"], "observed": "true"}
    ).json()

    assert repository["repository"] == "niranjankagri/cypress-typescript-framework"
    assert repository["observed_requirements"] == len(rows) > 0
    assert all(row["observed"] for row in rows)
    assert sum(repository["execution"].values()) == repository["observed_requirements"]
    for status, count in repository["execution"].items():
        matching = client.get(
            "/api/requirements",
            params={
                "repository": repository["repository"],
                "observed": "true",
                "execution_status": status,
            },
        ).json()
        assert len(matching) == count


def test_runs_carry_their_pipeline_job(client: TestClient) -> None:
    """Each run row says which pipeline and job it came from."""
    runs = client.get("/api/runs").json()

    assert {(r["pipeline"]["pipeline_id"], r["pipeline"]["job"]) for r in runs} >= {
        ("39238241112", "ui-firefox"),
        ("38842296207", "component"),
    }
    assert all(r["source"].startswith(f"{r['pipeline']['job']}/") for r in runs)


def test_an_oversized_job_list_is_refused(client: TestClient) -> None:
    """Query parameters are bounded like every other input."""
    assert client.get("/api/pipelines", params={"jobs": "x" * 2001}).status_code == 422


def test_repository_is_a_facet_and_a_filter(client: TestClient) -> None:
    """The selector's values come from the data; choosing one keeps its runs, another none."""
    facets = client.get("/api/facets").json()

    assert facets["repositories"] == ["niranjankagri/cypress-typescript-framework"]
    assert (
        len(
            client.get(
                "/api/runs", params={"repository": "niranjankagri/cypress-typescript-framework"}
            ).json()
        )
        == 9
    )
    assert client.get("/api/runs", params={"repository": "niranjankagri/other"}).json() == []
    summary = client.get("/api/summary", params={"repository": "niranjankagri/other"}).json()
    assert summary["pass_rate"]["text"].startswith("n/a")


REPO = "niranjankagri/cypress-typescript-framework"


def record(
    pid: str, attempt: int, conclusion: str, state: str, day: int, problems: tuple[str, ...] = ()
) -> object:
    """A collection record of the TaskBoard workflow."""
    from datetime import UTC, datetime

    from qualityintel.models.collection import PipelineCollection

    return PipelineCollection(
        pipeline_id=pid,
        attempt=attempt,
        repository=REPO,
        workflow="ci.yml",
        run_number=10 + day,
        branch="main",
        commit="80e331e",
        conclusion=conclusion,
        url=f"https://github.com/{REPO}/actions/runs/{pid}",
        started_at=datetime(2026, 10, day, 10, tzinfo=UTC),
        collected_at=datetime(2026, 10, day, 12, tzinfo=UTC),
        state=state,  # type: ignore[arg-type]
        problems=problems,
    )


@pytest.fixture(scope="module")
def collected_workspace() -> Workspace:
    """The two pipelines plus collection records: attempts of one, and a cancelled run with nothing."""
    records = [
        record("39238241112", 1, "success", "complete", 19),
        record(
            "38842296207",
            1,
            "failure",
            "incomplete",
            16,
            ("job ui-firefox: artifact report-ui-firefox not found",),
        ),
        record(
            "38842296207",
            2,
            "cancelled",
            "incomplete",
            16,
            ("job ui-firefox: artifact report-ui-firefox not found",),
        ),
        record("40000000000", 1, "cancelled", "incomplete", 18, ("job api: artifact report-api not found",)),
    ]
    return Workspace(load_catalog(PIPELINES / "catalog.toml"), pipeline_runs(), collections=records)  # type: ignore[arg-type]


@pytest.fixture(scope="module")
def collected(collected_workspace: Workspace) -> TestClient:
    """The dashboard on ``collected_workspace``."""
    return TestClient(
        create_app(collected_workspace, collection_hours=26, collection_url="https://github.com/x/y/actions")
    )


def test_collected_pipelines_show_conclusion_links_and_attempts(collected: TestClient) -> None:
    """A cancelled run without any runs is listed (incomplete); links go to the exact run and commit."""
    body = collected.get("/api/pipelines").json()
    by_id = {p["pipeline_id"]: p for p in body["pipelines"]}

    assert body["status_counts"] == {"success": 1, "incomplete": 2}
    assert body["workflows"] == ["ci.yml"]
    empty = by_id["40000000000"]
    assert (empty["status"], empty["jobs"], empty["conclusion"]) == ("incomplete", [], "cancelled")
    assert empty["problems"] == ["job api: artifact report-api not found"]
    ok = by_id["39238241112"]
    assert ok["url"] == f"https://github.com/{REPO}/actions/runs/39238241112"
    assert ok["commit_url"] == f"https://github.com/{REPO}/commit/80e331e"
    assert [a["attempt"] for a in by_id["38842296207"]["attempts"]] == [1, 2]


def test_pipelines_filter_by_status_and_workflow(collected: TestClient) -> None:
    """status=incomplete keeps the two incomplete; an unknown workflow keeps none."""
    incomplete = collected.get("/api/pipelines", params={"status": "incomplete"}).json()["pipelines"]
    other = collected.get("/api/pipelines", params={"workflow": "nightly.yml"}).json()

    assert sorted(p["pipeline_id"] for p in incomplete) == ["38842296207", "40000000000"]
    assert other["pipelines"] == []
    assert other["status_counts"] == {}


def test_a_context_filter_hides_collected_pipelines_without_runs(collected: TestClient) -> None:
    """Nothing is known about the context of a run that uploaded nothing."""
    ids = {
        p["pipeline_id"]
        for p in collected.get("/api/pipelines", params={"browser": "chrome"}).json()["pipelines"]
    }

    assert "40000000000" not in ids


def test_collection_health_per_repository(collected: TestClient) -> None:
    """Last collection, overdue against the expected hours, 7-day counts and problems."""
    body = collected.get("/api/collection").json()
    (row,) = body["repositories"]

    assert body["workflow_url"] == "https://github.com/x/y/actions"
    assert row["repository"] == REPO
    assert row["last_collected_at"].startswith("2026-10-19T12")
    assert row["last_complete_collection_at"].startswith("2026-10-19T12")
    assert row["fresh"] is False  # the records are from October; now is later
    assert "more than the expected 26 h" in row["freshness"]


def test_job_is_a_facet_and_a_filter(client: TestClient) -> None:
    """The Job filter: values from the data; ui-firefox keeps only the one Firefox run."""
    assert "ui-firefox" in client.get("/api/facets").json()["jobs"]
    runs = client.get("/api/runs", params={"job": "ui-firefox"}).json()

    assert [r["pipeline"]["job"] for r in runs] == ["ui-firefox"]


def test_status_counts_the_collection_records_of_fixed_data(collected: TestClient) -> None:
    """Fixed data (a Workspace, not a database) reports the same records the pages show."""
    status = collected.get("/api/status").json()
    pipelines = collected.get("/api/pipelines").json()

    assert status["collections"] > 0
    assert status["latest_collection_at"] is not None
    assert status["collections"] == sum(len(p["attempts"]) for p in pipelines["pipelines"] if p["attempts"])


def test_collection_problems_point_to_their_run_attempt(
    collected_workspace: Workspace, collected: TestClient
) -> None:
    """Each problem names its pipeline and attempt and links that attempt's page on GitHub.

    Only the last 7 days' records count, so the clock is fixed one day after the newest record
    (with the real clock this test began failing on 26 Oct 2026, 7 days after the records).
    """
    rows = collected_workspace.collection_health(now=datetime(2026, 10, 20, tzinfo=UTC)).repositories
    issues = [issue for row in rows for issue in row.issues]

    assert len(issues) == 3
    assert len(issues) == sum(len(row.problems) for row in rows)
    for issue in issues:
        assert issue.run_url is not None
        assert issue.run_url.startswith(f"https://github.com/{REPO}/actions/runs/")
        assert issue.run_url.endswith(f"/attempts/{issue.attempt}")
        assert issue.text
    api_rows = collected.get("/api/collection").json()["repositories"]
    assert all(len(row["issues"]) == len(row["problems"]) for row in api_rows)


def test_one_pipeline_can_be_focused_and_its_build_lists_its_github_run(collected: TestClient) -> None:
    """pipeline=<id> keeps that pipeline only; workflows are still offered for the selector."""
    every = collected.get("/api/pipelines").json()
    first = every["pipelines"][0]["pipeline_id"]
    focused = collected.get("/api/pipelines", params={"pipeline": first}).json()

    assert [p["pipeline_id"] for p in focused["pipelines"]] == [first]
    assert focused["workflows"] == every["workflows"]
    assert collected.get("/api/pipelines", params={"pipeline": "no-such"}).json()["pipelines"] == []


def test_build_cards_name_their_github_runs_and_incomplete_pipelines(collected: TestClient) -> None:
    """Each side of a comparison links the run attempts of its pipelines; incomplete ones are named."""
    builds = collected.get("/api/builds").json()
    body = collected.get("/api/compare", params={"base": builds[0], "head": builds[-1]}).json()
    sides = [body["base"], body["head"]]

    assert all(
        url.startswith(f"https://github.com/{REPO}/actions/runs/")
        for side in sides
        for url in side["ci_runs"]
    )
    assert all("/attempts/" in url for side in sides for url in side["ci_runs"])
    assert any(side["ci_runs"] for side in sides)
    assert any("38842296207 attempt 1" in side["incomplete_pipelines"] for side in sides)
