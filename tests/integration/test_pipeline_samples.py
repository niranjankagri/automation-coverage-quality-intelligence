"""Phase 6 acceptance on real pipelines: a complete one, and one whose Firefox job was cancelled.

samples/pipelines/cypress-taskboard holds every report of two GitHub Actions runs of the
TaskBoard Cypress project (samples/README.md): run 39238241112 (all five test jobs passed) and
run 38842296207 (cancelled by a newer push; the Firefox UI job uploaded no report).
"""

import json
from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, EXIT_OK, main
from qualityintel.history.store import HistoryStore
from qualityintel.traceability.pipelines import PipelineState, pipeline_execution

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2] / "samples" / "pipelines" / "cypress-taskboard"
COMPLETE = ROOT / "2026-10-19_80e331e_39238241112"
CANCELLED = ROOT / "2026-10-16_a15d3c7_38842296207"
JOBS = ["api", "ui-chrome", "ui-firefox", "ui-edge", "component"]


def job_args(folder: Path) -> list[str]:
    """``--pipeline <run id> --commit <sha> --job <name>=<file> ...`` for one sample run."""
    _, commit, run_id = folder.name.split("_")
    args = ["--pipeline", run_id, "--commit", commit]
    for report in sorted(folder.glob("*.json")):
        args += ["--job", f"{report.stem}={report}"]
    return args


def gate(tmp_path: Path, *args: str, config: Path = ROOT / "gate.toml") -> tuple[int, dict[str, object]]:
    """Run the TaskBoard gate; exit code and JSON report."""
    out = tmp_path / "gate.json"
    code = main(
        ["gate", "--catalog", str(ROOT / "catalog.toml"), "--config", str(config), "--json", str(out), *args]
    )
    return code, json.loads(out.read_text(encoding="utf-8"))


def test_the_samples_are_what_they_claim() -> None:
    """Five reports in the complete run, four in the cancelled one (no Firefox)."""
    assert sorted(p.stem for p in COMPLETE.glob("*.json")) == sorted(JOBS)
    assert sorted(p.stem for p in CANCELLED.glob("*.json")) == sorted(set(JOBS) - {"ui-firefox"})


def test_complete_pipeline_passes_with_every_job_counted(tmp_path: Path) -> None:
    """147 results: each job's own total, none lost to the latest-run-per-context rule."""
    code, data = gate(tmp_path, *job_args(COMPLETE))

    assert code == EXIT_OK
    pipeline = data["pipeline"]
    assert isinstance(pipeline, dict)
    assert pipeline["state"] == "complete"
    totals = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))["stats"]["passes"] for p in COMPLETE.glob("*.json")
    }
    assert {job["name"]: job["outcomes"]["passed"] for job in pipeline["jobs"]} == totals
    assert data["metrics"]["outcomes"]["passed"] == sum(totals.values()) == 147  # type: ignore[index]


def test_cancelled_pipeline_is_incomplete_although_everything_that_reported_passed(tmp_path: Path) -> None:
    """114 of 114 passed, but the Firefox job never reported: no decision (exit 3)."""
    code, data = gate(tmp_path, *job_args(CANCELLED))

    assert code == EXIT_INPUT
    assert data["gate"]["status"] == "incomplete"  # type: ignore[index]
    assert data["metrics"]["execution_pass_rate"]["text"] == "100.0 % (114/114)"  # type: ignore[index]
    assert data["input_problems"] == [
        "pipeline 38842296207: job ui-firefox reported no results (not run, cancelled or interrupted)"
    ]


def test_without_pipeline_grouping_the_cancelled_run_would_have_been_released(tmp_path: Path) -> None:
    """The risk this phase removes: a typical gate on the reports that exist says PASSED."""
    plain = tmp_path / "plain.toml"
    plain.write_text(
        "[coverage]\nmin_automated_requirement_coverage = 100\nmax_uncovered_critical = 0\n"
        "[execution]\nmin_pass_rate = 100\nmax_failing_critical = 0\n",
        encoding="utf-8",
    )

    code, _ = gate(tmp_path, str(CANCELLED), config=plain)

    assert code == EXIT_OK


def test_both_pipelines_go_into_history_and_come_back_as_executions(tmp_path: Path) -> None:
    """Stored with their jobs; read back from the database, each pipeline has the same state."""
    database = tmp_path / "h.db"
    for folder in (COMPLETE, CANCELLED):
        assert main(["history", "import", "--database", str(database), *job_args(folder)]) == EXIT_OK

    with HistoryStore(database) as store:
        runs = store.runs()

    complete = pipeline_execution(runs, "39238241112", JOBS)
    cancelled = pipeline_execution(runs, "38842296207", JOBS)
    assert (complete.state, len(complete.runs), complete.commit) == (PipelineState.COMPLETE, 5, "80e331e")
    assert (cancelled.state, cancelled.missing) == (PipelineState.INCOMPLETE, ("ui-firefox",))


def test_a_report_imported_again_under_another_job_attempt_is_refused(tmp_path: Path) -> None:
    """The cancelled run's API report imported as the complete run's API job: refused (exit 3)."""
    database = str(tmp_path / "h.db")
    assert main(["history", "import", "--database", database, *job_args(COMPLETE)]) == EXIT_OK

    code = main(
        [
            "history",
            "import",
            "--database",
            database,
            "--pipeline",
            "39238241112",
            "--job",
            f"api={CANCELLED / 'api.json'}",
        ]
    )

    assert code == EXIT_INPUT
