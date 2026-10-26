"""Workflow recovery must not rewrite or conceal missing historical evidence."""

from datetime import UTC, datetime, timedelta

import pytest

from qualityintel.collect.health import recovered_workflows
from qualityintel.models.collection import PipelineCollection

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 26, tzinfo=UTC)


def record(number: int = 1, **changes: object) -> PipelineCollection:
    """A recorded main-branch workflow attempt, overridable for scope regressions."""
    values: dict[str, object] = {
        "pipeline_id": f"repo#{number}",
        "attempt": 1,
        "repository": "owner/repo",
        "workflow": "tests.yml",
        "branch": "main",
        "run_number": number,
        "started_at": NOW + timedelta(hours=number),
        "collected_at": NOW + timedelta(days=1),
        "conclusion": "cancelled",
        "state": "incomplete",
        "problems": ("missing report",),
    }
    values.update(changes)
    return PipelineCollection.model_validate(values)


@pytest.mark.parametrize("conclusion", ["cancelled", "failure", "success"])
def test_later_complete_success_resolves_operational_alert_only(conclusion: str) -> None:
    """A recovered workflow is distinguished from repaired historical data."""
    missing = record(conclusion=conclusion)
    before = missing.model_dump_json()
    complete = record(2, state="complete", conclusion="success", problems=())
    assert recovered_workflows([missing, complete]) == {(missing.pipeline_id, 1): complete}
    assert missing.model_dump_json() == before
    assert missing.state == "incomplete"


@pytest.mark.parametrize(
    "changes",
    [
        {"repository": "other/repo"},
        {"workflow": "other.yml"},
        {"branch": "feature"},
        {"state": "incomplete"},
        {"conclusion": "failure"},
        {"started_at": None},
        {"run_number": 0},
        {"started_at": NOW},
    ],
)
def test_unrelated_or_unordered_evidence_cannot_resolve(changes: dict[str, object]) -> None:
    """A same-day collection or unrelated successful workflow is not recovery evidence."""
    values: dict[str, object] = {"state": "complete", "conclusion": "success", "problems": ()}
    values.update(changes)
    complete = record(2, **values)
    assert not recovered_workflows([record(), complete])


def test_older_complete_run_and_missing_branch_do_not_resolve() -> None:
    """Only a later execution of an identified branch can close the operational alert."""
    assert not recovered_workflows([record(2), record(1, state="complete", conclusion="success")])
    assert not recovered_workflows([record(branch=""), record(2, state="complete", conclusion="success")])


def test_successful_later_attempt_of_same_pipeline_resolves() -> None:
    """A complete rerun is linked to the original incomplete attempt."""
    complete = record(attempt=2, state="complete", conclusion="success", problems=())
    assert recovered_workflows([record(), complete]) == {("repo#1", 1): complete}


def test_status_keeps_raw_history_and_explains_recovery() -> None:
    """Public status reconciles raw, active and recovered counts without hiding problems."""
    from pathlib import Path

    from fastapi.testclient import TestClient

    from qualityintel.dashboard.app import create_app
    from qualityintel.ingest.catalog_file import load_catalog
    from qualityintel.workspace import Workspace

    missing = record(collected_at=datetime.now(UTC))
    complete = record(2, state="complete", conclusion="success", problems=())
    active = record(3, collected_at=datetime.now(UTC))
    workspace = Workspace(
        load_catalog(Path(__file__).parents[3] / "samples" / "catalog.toml"),
        [],
        collections=[missing, complete, active],
    )
    with TestClient(create_app(workspace)) as client:
        status = client.get("/api/status").json()
    assert status["incomplete_collections_7d"] == 2
    assert status["unresolved_incomplete_collections_7d"] == 1
    assert status["recovered_workflow_collections_7d"] == 1
    assert len(status["collection_resolutions"]) == 1
    assert "repo#1" in status["collection_resolutions"][0]
    assert "repo#2" in status["collection_resolutions"][0]
    assert len(status["collection_problems"]) == 2
