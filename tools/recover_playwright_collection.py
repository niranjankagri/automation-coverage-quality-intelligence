"""Recover one historical JUnit collection to a new database, retaining a full audit trail.

The original producer contract predates the 26 Oct JSON migration. Existing executions must
match exactly; only the missing Chromium job may be added. Input files are never modified.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from qualityintel.collect.collector import _collect_run
from qualityintel.collect.config import Producer
from qualityintel.collect.github import Artifact, GitHubActions
from qualityintel.history.store import HistoryError, HistoryStore

REPOSITORY = "niranjankagri/playwright-typescript-framework"
PIPELINE = "playwright-typescript-framework#39927750283"
RUN = 39927750283
ATTEMPT = 2
COMMIT = "9c9675c8e11f62ad80615728dd3bcf3aef230105"


class EvidenceSource(GitHubActions):
    """Record the exact downloaded bytes and artifact provenance without logging credentials."""

    def __init__(self, token: str | None) -> None:
        super().__init__(token)
        self.evidence: dict[str, str] = {}

    def download(self, repository: str, artifact: Artifact, target: Path) -> Path:
        """Download through the existing bounded client, then retain its content hash."""
        path = super().download(repository, artifact, target)
        self.evidence[str(artifact.id)] = json.dumps(
            {
                "name": artifact.name,
                "created_at": str(artifact.created_at),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            },
            sort_keys=True,
        )
        return path


def recover(database: Path, output: Path, source: EvidenceSource) -> bool:
    """Write a recovered copy only after every invariant passes; return false when already recovered.

    Raises:
        HistoryError: The source identity, original results or retained reports disagree.
    """
    if database.resolve() == output.resolve() or output.exists():
        raise HistoryError("output must be a new file, separate from the input history")
    if not database.is_file():
        raise HistoryError("input history is missing")
    if any(database.with_name(database.name + suffix).exists() for suffix in ("-wal", "-journal")):
        raise HistoryError("recovery requires a closed, offline history snapshot")
    with tempfile.TemporaryDirectory(prefix="qi-recovery-") as folder:
        copy = Path(folder) / "history.db"
        shutil.copy2(database, copy)
        with HistoryStore(copy) as store:
            previous = next(
                (c for c in store.collections() if c.pipeline_id == PIPELINE and c.attempt == ATTEMPT), None
            )
            if previous is None or previous.commit != COMMIT[:12]:
                raise HistoryError("the expected historical collection is missing or has another commit")
            if previous.state == "complete":
                audited = any(
                    json.loads(item["replacement_record"]) == previous.model_dump(mode="json")
                    and json.loads(item["previous_record"])["state"] == "incomplete"
                    and len(json.loads(item["evidence"])) >= 4
                    for item in store.collection_recoveries()
                )
                if (previous.runs, previous.results) != (4, 95) or not audited:
                    raise HistoryError("complete collection has no matching reviewed recovery audit")
                print("Already complete with a recovery audit; no history was changed.")
                return False
            if (previous.runs, previous.results) != (3, 71):
                raise HistoryError(
                    "the original partial collection differs from the reviewed 3-job/71-result record"
                )
            candidates = source.completed_runs(
                REPOSITORY, "ci.yml", "main", datetime(2026, 10, 23, tzinfo=UTC)
            )
            run = next((r for r in candidates if r.id == RUN and r.attempt == ATTEMPT), None)
            if run is None or run.commit != COMMIT[:12] or run.conclusion != "success":
                raise HistoryError("GitHub no longer identifies the reviewed successful run and attempt")
            producer = Producer.model_validate(
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
                        for name in ("api", "chromium", "firefox", "webkit")
                    ],
                }
            )
            with HistoryStore(Path(folder) / "assessment.db") as assessment:
                record = _collect_run(producer, run, source, assessment, datetime.now(UTC))
                if record.state != "complete" or (record.runs, record.results) != (4, 95):
                    raise HistoryError(
                        "retained artifacts do not establish the reviewed complete 4-job/95-result run"
                    )
                added = store.recover_collection(record, assessment.runs(), source.evidence)
            if added != 1 or store.check():
                raise HistoryError("recovered history failed its added-run or database-integrity check")
            expected_count = store.count()
            expected_audit = store.collection_recoveries()
            store.backup(output)
            with HistoryStore(output) as verified:
                if (
                    verified.check()
                    or verified.count() != expected_count
                    or verified.collection_recoveries() != expected_audit
                ):
                    raise HistoryError("output backup failed verification")
        print(
            "Recovered 1 retained Chromium job (24 results); "
            "original collection preserved in collection_recoveries."
        )
        return True


def main() -> None:
    """Run the reviewed one-off recovery and expose a publication flag to its workflow."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    changed = recover(args.database, args.output, EvidenceSource(os.environ.get("GITHUB_TOKEN")))
    if destination := os.environ.get("GITHUB_OUTPUT"):
        with Path(destination).open("a", encoding="utf-8") as stream:
            stream.write(f"changed={str(changed).lower()}\n")


if __name__ == "__main__":
    main()
