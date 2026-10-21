"""A writer killed in the middle of an import leaves a consistent history (docs/operations.md).

The writer stores the sample runs one transaction each and says so after every run; it is
killed (no clean shutdown) after the fifth. SQLite must then report no damage, and every stored
run must hold exactly the results of its file: no half-written run, no result without its run.
"""

import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path

import pytest

from qualityintel.ingest.batch import import_results

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).parents[2] / "samples" / "results"
WRITER = """
import sys
from qualityintel.history.store import HistoryStore
from qualityintel.ingest.batch import import_results
runs = import_results([sys.argv[1]]).runs
with HistoryStore(sys.argv[2]) as store:
    for run in runs:
        store.add(run)
        print("stored", flush=True)
"""


def test_a_killed_import_leaves_only_whole_runs(tmp_path: Path) -> None:
    """Killed after five stored runs: integrity ok, no orphans, each run complete."""
    database = tmp_path / "history.db"
    expected = {run.run_id: len(run.results) for run in import_results([SAMPLES]).runs}
    writer = subprocess.Popen(
        [sys.executable, "-c", WRITER, str(SAMPLES), str(database)], stdout=subprocess.PIPE, text=True
    )
    assert writer.stdout is not None
    for _ in range(5):
        assert writer.stdout.readline().strip() == "stored"
    writer.kill()
    writer.wait()
    writer.stdout.close()

    with closing(sqlite3.connect(database)) as db:
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert db.execute("PRAGMA foreign_key_check").fetchall() == []
        stored = dict(db.execute("SELECT run_id, COUNT(*) FROM results GROUP BY run_id").fetchall())
        runs = db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    assert 5 <= runs < len(expected)
    assert all(count == expected[run_id] for run_id, count in stored.items())
