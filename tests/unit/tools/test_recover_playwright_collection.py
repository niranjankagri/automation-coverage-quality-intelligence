"""Exercise the recovery command using retained-style JUnit artifacts, without network access."""

import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from qualityintel.collect.collector import _collect_run
from qualityintel.collect.config import Producer
from qualityintel.collect.github import Artifact, WorkflowRun
from qualityintel.history.store import HistoryError, HistoryStore

sys.path.insert(0, str(Path(__file__).parents[3] / "tools"))
from recover_playwright_collection import ATTEMPT, COMMIT, REPOSITORY, RUN, EvidenceSource, recover

pytestmark = pytest.mark.unit
WHEN = datetime(2026, 10, 23, 10, tzinfo=UTC)
EXECUTION = WorkflowRun(
    RUN,
    ATTEMPT,
    23,
    "schedule",
    "main",
    COMMIT[:12],
    "success",
    f"https://github.com/{REPOSITORY}/actions/runs/{RUN}",
    WHEN,
)
JOBS = ("api", "chromium", "firefox", "webkit")
PRODUCER = Producer.model_validate(
    {
        "repository": REPOSITORY,
        "workflow": "ci.yml",
        "context": {"framework": "playwright", "environment": "ci", "platform": "linux"},
        "job": [
            {
                "name": name,
                "artifact": "junit-" + name,
                "path": ".",
                "context": {"browser": name} if name != "api" else {},
            }
            for name in JOBS
        ],
    }
)


class RetainedSource(EvidenceSource):
    """Four small report archives; the original import has no Chromium artifact."""

    def __init__(self, missing: bool = False) -> None:
        super().__init__(None)
        self.missing = missing

    def completed_runs(
        self, repository: str, workflow: str, branch: str, since: datetime
    ) -> list[WorkflowRun]:
        """Return the reviewed attempt."""
        return [EXECUTION]

    def artifacts(self, repository: str, run_id: int) -> list[Artifact]:
        """Return expected artifact metadata."""
        return [
            Artifact(i, "junit-" + name, 100, False, WHEN)
            for i, name in enumerate(JOBS, 1)
            if not (self.missing and name == "chromium")
        ]

    def download(self, repository: str, artifact: Artifact, target: Path) -> Path:
        """Write distinct, valid report bytes with a verifiable content hash."""
        name = artifact.name.removeprefix("junit-")
        count = 23 if name == "webkit" else 24
        cases = "".join(f'<testcase classname="{name}" name="case-{i}" time="0.1"/>' for i in range(count))
        with zipfile.ZipFile(target, "w") as archive:
            archive.writestr("junit.xml", f'<testsuite name="{name}" tests="{count}">{cases}</testsuite>')
        self.evidence[str(artifact.id)] = json.dumps(
            {"name": name, "sha256": hashlib.sha256(target.read_bytes()).hexdigest()}
        )
        return target


def test_command_keeps_input_bytes_and_audits_a_recoverable_attempt(tmp_path: Path) -> None:
    """A fresh output gains 24 real results; rerunning on that output is a no-op."""
    original, output = tmp_path / "original.db", tmp_path / "recovered.db"
    with HistoryStore(original) as store:
        _collect_run(PRODUCER, EXECUTION, RetainedSource(missing=True), store, WHEN)
        assert store.count() == (3, 71)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    assert recover(original, output, RetainedSource())
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
    with HistoryStore(output) as store:
        assert store.count() == (4, 95)
        assert len(store.collection_recoveries()) == 1
        assert not store.check()
    assert not recover(output, tmp_path / "unused.db", RetainedSource())
    assert not (tmp_path / "unused.db").exists()
    with pytest.raises(HistoryError, match="new file"):
        recover(original, original, RetainedSource())
    with pytest.raises(HistoryError, match="new file"):
        recover(original, output, RetainedSource())


def test_missing_evidence_cannot_produce_a_publication_file(tmp_path: Path) -> None:
    """A failed reimport leaves the original untouched and creates no replacement file."""
    original, output = tmp_path / "original.db", tmp_path / "output.db"
    with HistoryStore(original) as store:
        _collect_run(PRODUCER, EXECUTION, RetainedSource(missing=True), store, WHEN)
    digest = hashlib.sha256(original.read_bytes()).hexdigest()
    with pytest.raises(HistoryError, match="retained artifacts"):
        recover(original, output, RetainedSource(missing=True))
    assert not output.exists()
    assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
