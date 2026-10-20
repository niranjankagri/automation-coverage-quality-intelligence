"""``/api/pipelines`` and pipeline fields of ``/api/runs`` on the two real TaskBoard pipelines."""

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
