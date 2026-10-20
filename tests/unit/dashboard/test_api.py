"""The JSON API, through FastAPI's TestClient (no server, no browser)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qualityintel.dashboard.app import CONTENT_SECURITY_POLICY, create_app
from qualityintel.workspace import Workspace

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[3] / "samples"
NO_RUN = "0" * 64


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The sample workspace behind a test client."""
    workspace, batch = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    assert batch.complete
    return TestClient(create_app(workspace))


def test_health_reports_the_loaded_data(client: TestClient) -> None:
    """42 requirements and 43 runs are loaded."""
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert (body["requirements"], body["runs"]) == (42, 43)


def test_summary_numbers_match_the_traceability_engine(client: TestClient) -> None:
    """Same values as `qi coverage` (checked independently in tests/integration)."""
    body = client.get("/api/summary").json()

    assert body["requirement_coverage"]["text"] == "90.5 % (38/42)"
    assert body["automation_coverage"]["text"] == "86.0 % (37/43)"
    assert body["automated_requirement_coverage"]["text"] == "76.2 % (32/42)"
    assert [r["id"] for r in body["uncovered_critical"]] == ["SHOP-008", "ADMIN-012"]
    assert body["pass_rate"]["text"] == "100.0 % (221/221)"


def test_filters_are_repeatable_query_parameters(client: TestClient) -> None:
    """Two criticalities at once (13 critical + 16 high); the scope shrinks accordingly."""
    body = client.get("/api/summary?criticality=critical&criticality=high").json()

    assert body["requirements_total"] == 29


def test_requirement_status_drill_down(client: TestClient) -> None:
    """status=no tests lists exactly the four requirements without tests."""
    rows = client.get("/api/requirements", params={"status": "no tests"}).json()

    assert [r["id"] for r in rows] == ["NOTES-012", "SHOP-010", "ADMIN-010", "ADMIN-012"]


def test_requirement_detail_and_404(client: TestClient) -> None:
    """A known id gives its test cases; an unknown id gives 404 with a message."""
    detail = client.get("/api/requirements/SHOP-006").json()
    missing = client.get("/api/requirements/NOPE-1")

    assert [c["id"] for c in detail["test_cases"]] == ["TC-SHOP-CHECKOUT"]
    assert detail["test_cases"][0]["execution_status"] == "passing"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "unknown requirement 'NOPE-1'"


def test_test_history_by_key_in_the_query(client: TestClient) -> None:
    """The Selenium test that failed on 13 Oct shows that failure in its history."""
    key = "com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer"

    history = client.get("/api/tests/history", params={"key": key}).json()

    outcomes = [e["outcome"] for e in history["executions"]]
    assert len(outcomes) == 13
    assert outcomes.count("failed") == 1
    assert history["test_cases"] == ["TC-ADMIN-CUSTOMERS-UI"]
    assert client.get("/api/tests/history", params={"key": "nope"}).status_code == 404


def test_tests_list_puts_failing_tests_first(client: TestClient) -> None:
    """Tests with failures or errors anywhere in the history come first."""
    rows = client.get("/api/tests").json()

    assert rows[0]["failed"] + rows[0]["errors"] > 0
    assert len(rows) == 221


def test_runs_and_run_detail(client: TestClient) -> None:
    """Runs newest first; a run detail lists failures before passes; unknown run is 404."""
    runs = client.get("/api/runs", params={"framework": "playwright"}).json()
    attempt1 = next(r for r in runs if r["source"].endswith("39229363499-attempt1.xml"))
    detail = client.get(f"/api/runs/{attempt1['run_id']}").json()

    assert len(runs) == 5
    assert detail["executions"][0]["outcome"] == "failed"
    assert client.get(f"/api/runs/{NO_RUN}").status_code == 404


@pytest.mark.parametrize(
    ("path", "query"),
    [
        ("/api/summary", "criticality=urgent"),
        ("/api/summary", "test_type=manual"),
        ("/api/requirements", "status=done"),
        ("/api/tests", "outcome=green"),
    ],
)
def test_impossible_filter_values_are_rejected(client: TestClient, path: str, query: str) -> None:
    """A value that can never match is a 422 with an explanation, not an empty answer."""
    response = client.get(f"{path}?{query}")

    assert response.status_code == 422


def test_unknown_but_possible_values_give_an_empty_scope(client: TestClient) -> None:
    """A browser nobody used is a valid question with an empty answer (n/a pass rate)."""
    body = client.get("/api/summary?browser=safari").json()

    assert body["snapshot"] == []
    assert body["pass_rate"]["percent"] is None


def test_front_end_is_served_with_a_strict_content_security_policy(client: TestClient) -> None:
    """The page, its script and stylesheet come from this server; no inline code is allowed."""
    page = client.get("/")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert '<script src="/static/app.js" defer></script>' in page.text
    assert page.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert script.headers["x-content-type-options"] == "nosniff"
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY


def test_openapi_documentation_lists_every_route(client: TestClient) -> None:
    """/docs is generated from the routes, so it cannot drift from the API."""
    paths = set(client.get("/openapi.json").json()["paths"])

    assert paths == {
        "/api/health",
        "/api/facets",
        "/api/summary",
        "/api/requirements",
        "/api/requirements/{requirement_id}",
        "/api/tests",
        "/api/tests/history",
        "/api/runs",
        "/api/runs/{run_id}",
        "/api/stability",
    }


def test_stability_lists_the_real_flaky_candidates(client: TestClient) -> None:
    """Four flaky candidates with reasons; stable tests are left out unless asked for."""
    body = client.get("/api/stability").json()

    assert body["status_counts"] == {"flaky candidate": 4, "stable": 217}
    assert len(body["rows"]) == 4
    edits = next(r for r in body["rows"] if r["key"].endswith("adminEditsACustomer"))
    assert edits["context"] == "testng / ci / firefox / linux"
    assert edits["test_cases"] == ["TC-ADMIN-CUSTOMERS-UI"]
    assert "passed and failed on the same build (f5a40d5)" in edits["reasons"]
    assert len(client.get("/api/stability?include_stable=true").json()["rows"]) == 221


def test_stability_window_and_trends(client: TestClient) -> None:
    """A window of 3 forgets the 13 Oct failure; trends have one series per context."""
    body = client.get("/api/stability", params={"window": 3}).json()

    assert body["window"] == 3
    assert not any(r["key"].endswith("adminEditsACustomer") for r in body["rows"])
    assert len(body["trends"]) == 5
    assert len(body["trends"]["testng / ci / firefox / linux"]) == 13
    assert client.get("/api/stability", params={"window": 0}).status_code == 422
