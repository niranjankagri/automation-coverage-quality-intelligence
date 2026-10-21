"""Copyable investigation summaries: grounded, deterministic, escaped (docs/dashboard.md, Summaries)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qualityintel.dashboard.app import create_app
from qualityintel.reporting.investigation import summarise_comparison, summarise_test
from qualityintel.workspace import Workspace

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[2] / "samples"
TEST_KEY = "com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer"
AS_OF = datetime(2026, 10, 21, 5, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    """The sample results with the sample catalog."""
    loaded, _ = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    return loaded


def test_a_test_summary_states_observations_counts_and_limits(workspace: Workspace) -> None:
    """Latest and previous outcome, history counts that add up, the suspicion as a suspicion."""
    history = workspace.test_history(TEST_KEY)
    summary = summarise_test(history, AS_OF, "https://example.org/#/test", workspace.catalog.notice)
    lines = summary.text.splitlines()

    assert lines[0] == f"Investigation: {TEST_KEY}"
    assert (
        f"History in scope: {len(history.executions)} execution(s): {history.passed} passed" in summary.text
    )
    assert "flaky candidate (suspected)" in summary.text
    assert "Requirements: ADMIN-003" in summary.text
    assert "Dashboard: https://example.org/#/test" in summary.text
    assert "Data as of: 2026-10-21 05:00 UTC" in summary.text
    assert "no cause is inferred" in summary.text
    assert "synthetic sample catalog" in summary.text  # the catalog's own notice
    for invented in ("root cause", "because", "severity", "critical"):
        assert invented not in summary.text.lower().replace("no cause is inferred", "")


def test_the_same_input_gives_the_same_summary(workspace: Workspace) -> None:
    """Deterministic: two calls, identical text and Markdown."""
    history = workspace.test_history(TEST_KEY)

    assert summarise_test(history, AS_OF) == summarise_test(history, AS_OF)


def test_markdown_escapes_imported_text(workspace: Workspace) -> None:
    """A test named like a link stays text in Markdown; plain text keeps it as it is."""
    history = workspace.test_history(TEST_KEY)
    hostile = history.model_copy(update={"key": "[click](https://evil.example)"})
    summary = summarise_test(hostile, AS_OF)

    assert "\\[click\\]\\(https://evil.example\\)" in summary.markdown
    assert "[click](https://evil.example)" in summary.text  # plain text: nothing renders it


def test_a_comparison_summary_lists_changes_by_category_with_counts(workspace: Workspace) -> None:
    """The categories and counts of the Compare page; incomparable builds say so."""
    comparison = workspace.compare_builds("f5a40d5", "1d03232")
    summary = summarise_comparison(comparison, AS_OF)
    slower = [c for c in comparison.changes if c.category == "slower"]

    assert summary.text.startswith("Build comparison: f5a40d5 vs 1d03232")
    assert f"Slower ({len(slower)}):" in summary.text
    assert "Comparable suites: 1: testng/ci/firefox/linux" in summary.text


def test_the_summary_api_accepts_only_web_links_and_known_entities(workspace: Workspace) -> None:
    """A javascript: link is dropped; unknown tests and builds are 404; equal builds 422."""
    client = TestClient(create_app(workspace))

    bad = client.get("/api/tests/summary", params={"key": TEST_KEY, "link": "javascript:alert(1)"}).json()
    assert "javascript:" not in bad["text"] + bad["markdown"]
    assert client.get("/api/tests/summary", params={"key": "no::such"}).status_code == 404
    assert client.get("/api/compare/summary", params={"base": "x", "head": "x"}).status_code == 422
    assert client.get("/api/compare/summary", params={"base": "f5a40d5", "head": "nope"}).status_code == 404


def test_new_routes_need_the_login_when_one_is_set(workspace: Workspace) -> None:
    """Search, Needs Attention and summaries are behind the same basic authentication."""
    client = TestClient(create_app(workspace, ("qi", "correct horse battery")))

    for path in ("/api/search?q=checkout", "/api/attention", f"/api/tests/summary?key={TEST_KEY}"):
        assert client.get(path).status_code == 401, path
        assert client.get(path, auth=("qi", "correct horse battery")).status_code == 200, path


def test_the_investigation_names_workflow_and_stability(workspace: Workspace) -> None:
    """Each execution carries its workflow when collected; the history carries stability lines."""
    history = workspace.test_history(TEST_KEY)

    assert history.stability
    assert all(line.split(":")[0] for line in history.stability)
    assert all(e.workflow is None for e in history.executions)  # the samples were not collected
