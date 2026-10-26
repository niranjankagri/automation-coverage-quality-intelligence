"""Recovery adds retained missing evidence while preserving an auditable original."""

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from qualityintel.history.store import HistoryError, HistoryStore
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.results import PipelineJob, TestRun

from ..traceability.helpers import result, run

pytestmark = pytest.mark.unit
NOW = datetime(2026, 10, 26, tzinfo=UTC)


def evidence() -> tuple[PipelineCollection, PipelineCollection, TestRun, TestRun]:
    """A partial attempt and the same attempt with a retained missing UI report."""
    job = PipelineJob(
        pipeline_id="example#123",
        job="api",
        attempt=2,
        branch="main",
        commit="abc",
        repository="owner/example",
    )
    first = run(result("api check"), source="api.xml").model_copy(update={"pipeline": job})
    second = run(result("ui check"), source="ui.xml").model_copy(
        update={"pipeline": job.model_copy(update={"job": "ui"})}
    )
    old = PipelineCollection(
        pipeline_id="example#123",
        attempt=2,
        repository="owner/example",
        workflow="ci.yml",
        run_number=3,
        event="push",
        branch="main",
        commit="abc",
        conclusion="success",
        url="https://github.com/owner/example/actions/runs/123",
        started_at=NOW - timedelta(days=2),
        collected_at=NOW - timedelta(days=1),
        state="incomplete",
        runs=1,
        results=1,
        problems=("UI artifact ambiguous",),
    )
    new = old.model_copy(
        update={"collected_at": NOW, "state": "complete", "runs": 2, "results": 2, "problems": ()}
    )
    return old, new, first, second


def test_recovery_adds_missing_evidence_and_keeps_original_audit(tmp_path: Path) -> None:
    """Existing rows survive exactly, and both collection versions remain inspectable."""
    old, new, first, second = evidence()
    with HistoryStore(tmp_path / "h.db") as store:
        store.add_collection(old, [first])
        assert store.recover_collection(new, [first, second], {"artifact": "456", "sha256": "abc"}) == 1
        assert store.count() == (2, 2)
        assert first in store.runs()
        assert store.collections() == [new]
        audit = store.collection_recoveries()[0]
        assert json.loads(audit["previous_record"]) == old.model_dump(mode="json")
        assert json.loads(audit["replacement_record"]) == new.model_dump(mode="json")
        assert json.loads(audit["evidence"]) == {"artifact": "456", "sha256": "abc"}
        with pytest.raises(HistoryError, match="existing incomplete"):
            store.recover_collection(new, [first, second], {"artifact": "456"})


@pytest.mark.parametrize(
    "change",
    ["identity", "counts", "payload", "missing", "scope", "incomplete", "no_evidence", "conflicting_job"],
)
def test_invalid_recovery_changes_nothing(tmp_path: Path, change: str) -> None:
    """A claimed recovery must not hide a changed result, missing job or wrong attempt."""
    old, new, first, second = evidence()
    items = [first, second]
    manifest = {"artifact": "456"}
    if change == "identity":
        new = new.model_copy(update={"commit": "different"})
    elif change == "counts":
        new = new.model_copy(update={"results": 99})
    elif change == "payload":
        items[0] = first.model_copy(update={"results": (result("changed"),)})
    elif change == "missing":
        items = [second]
        new = new.model_copy(update={"runs": 1, "results": 1})
    elif change == "scope":
        assert first.pipeline is not None
        items[1] = second.model_copy(update={"pipeline": first.pipeline.model_copy(update={"attempt": 3})})
    elif change == "incomplete":
        new = new.model_copy(update={"state": "incomplete"})
    elif change == "no_evidence":
        manifest = {}
    elif change == "conflicting_job":
        items[1] = second.model_copy(update={"pipeline": first.pipeline})
    with HistoryStore(tmp_path / "h.db") as store:
        store.add_collection(old, [first])
        with pytest.raises(HistoryError):
            store.recover_collection(new, items, manifest)
        assert store.count() == (1, 1)
        assert store.collections() == [old]
        assert store.collection_recoveries() == []


def test_recovery_rolls_back_added_runs_when_audit_cannot_be_written(tmp_path: Path) -> None:
    """A disk/SQL failure cannot leave added results without their recovery journal."""
    old, new, first, second = evidence()
    with HistoryStore(tmp_path / "h.db") as store:
        store.add_collection(old, [first])
        store._db.execute(
            "CREATE TRIGGER fail_audit BEFORE INSERT ON collection_recoveries BEGIN SELECT RAISE(ABORT, 'disk failure'); END"
        )
        with pytest.raises(sqlite3.DatabaseError):
            store.recover_collection(new, [first, second], {"artifact": "456"})
        assert store.count() == (1, 1)
        assert store.collections() == [old]
        assert store.collection_recoveries() == []
