"""``--pipeline`` / ``--job``: gates on complete, failed and interrupted pipelines; history import."""

import json
from pathlib import Path

import pytest

from qualityintel.cli import EXIT_GATE_FAILED, EXIT_INPUT, EXIT_OK, EXIT_USAGE, main
from qualityintel.history.store import HistoryStore

pytestmark = pytest.mark.unit

CATALOG = """
[[requirement]]
id = "R1"
title = "API works"
criticality = "critical"

[[requirement]]
id = "R2"
title = "UI works"
criticality = "critical"

[[test_case]]
id = "TC-API"
title = "API tests"
automation_status = "automated"
requirements = ["R1"]
automated_by = ["api::*"]

[[test_case]]
id = "TC-UI"
title = "UI tests"
automation_status = "automated"
requirements = ["R2"]
automated_by = ["ui::*"]
"""

GATE = """
name = "release"
[execution]
max_failed_tests = 0
[pipeline]
jobs = ["api", "ui-chrome"]
"""


def junit(path: Path, classname: str, failed: bool = False, stamp: str = "2026-10-19T09:00:00") -> str:
    """Write a JUnit file with one test; returns its path."""
    body = "<failure message='boom'/>" if failed else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"<testsuite name='s' timestamp='{stamp}'><testcase classname='{classname}' name='t'>{body}</testcase></testsuite>",
        encoding="utf-8",
    )
    return str(path)


@pytest.fixture
def setup(tmp_path: Path) -> dict[str, str]:
    """Catalog, gate file and one result file per job (API and Chrome UI)."""
    (tmp_path / "catalog.toml").write_text(CATALOG, encoding="utf-8")
    (tmp_path / "gate.toml").write_text(GATE, encoding="utf-8")
    return {
        "catalog": str(tmp_path / "catalog.toml"),
        "gate": str(tmp_path / "gate.toml"),
        "api": junit(tmp_path / "artifacts" / "api" / "junit.xml", "api"),
        "ui": junit(tmp_path / "artifacts" / "ui-chrome" / "junit.xml", "ui"),
        "dir": str(tmp_path),
    }


def gate(setup: dict[str, str], *args: str) -> list[str]:
    """``qi gate`` arguments with the catalog, the gate file and a JSON report."""
    return [
        "gate",
        "--catalog",
        setup["catalog"],
        "--config",
        setup["gate"],
        "--json",
        f"{setup['dir']}/gate.json",
        *args,
    ]


def report(setup: dict[str, str]) -> dict[str, object]:
    """The JSON report of the last gate."""
    return json.loads(Path(setup["dir"], "gate.json").read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def test_complete_pipeline_passes(setup: dict[str, str], capsys: pytest.CaptureFixture[str]) -> None:
    """Both jobs reported, nothing failed: exit 0, and the report shows the pipeline."""
    code = main(
        gate(
            setup,
            "--pipeline",
            "77",
            "--commit",
            "abc",
            "--job",
            f"api={setup['api']}",
            "--job",
            f"ui-chrome={setup['ui']}",
        )
    )

    assert code == EXIT_OK
    pipeline = report(setup)["pipeline"]
    assert isinstance(pipeline, dict)
    assert (pipeline["id"], pipeline["state"], pipeline["commit"]) == ("77", "complete", "abc")
    assert [job["name"] for job in pipeline["jobs"]] == ["api", "ui-chrome"]
    assert "pipeline 77 at abc: complete (2 job(s) reported)" in capsys.readouterr().out


def test_pipeline_with_a_failed_test_fails_the_gate(setup: dict[str, str], tmp_path: Path) -> None:
    """Complete pipeline, one failure: exit 1 (a decision), not incomplete."""
    failed = junit(tmp_path / "artifacts" / "ui-failed" / "junit.xml", "ui", failed=True)

    code = main(
        gate(setup, "--pipeline", "77", "--job", f"api={setup['api']}", "--job", f"ui-chrome={failed}")
    )

    assert code == EXIT_GATE_FAILED
    assert report(setup)["gate"]["status"] == "failed"  # type: ignore[index]


def test_interrupted_pipeline_is_incomplete_although_its_results_pass(
    setup: dict[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    """The UI job never reported: the passing API results alone must not release."""
    code = main(gate(setup, "--pipeline", "77", "--job", f"api={setup['api']}"))

    assert code == EXIT_INPUT
    data = report(setup)
    assert data["gate"]["status"] == "incomplete"  # type: ignore[index]
    assert data["input_problems"] == [
        "pipeline 77: job ui-chrome reported no results (not run, cancelled or interrupted)"
    ]
    assert "missing: ui-chrome" in capsys.readouterr().out


def test_a_job_whose_artifact_is_missing_is_incomplete(setup: dict[str, str]) -> None:
    """The job is named but its folder is not there (artifact upload failed)."""
    code = main(
        gate(
            setup,
            "--pipeline",
            "77",
            "--job",
            f"api={setup['api']}",
            "--job",
            f"ui-chrome={setup['dir']}/nowhere",
        )
    )

    assert code == EXIT_INPUT
    problems = report(setup)["input_problems"]
    assert isinstance(problems, list)
    assert any("nowhere" in p for p in problems)
    assert "pipeline 77: job ui-chrome reported no results (not run, cancelled or interrupted)" in problems


def test_gate_that_expects_jobs_refuses_plain_results(setup: dict[str, str]) -> None:
    """Results without --pipeline cannot show that every job reported."""
    code = main(gate(setup, setup["api"], setup["ui"]))

    assert code == EXIT_INPUT
    problems = report(setup)["input_problems"]
    assert isinstance(problems, list)
    assert "not given as a pipeline" in problems[0]


def test_jobs_named_on_the_command_line_are_expected_without_a_job_list(
    setup: dict[str, str], tmp_path: Path
) -> None:
    """Gate file without [pipeline]: the --job names are the jobs that must report."""
    plain = tmp_path / "plain.toml"
    plain.write_text("[execution]\nmax_failed_tests = 0\n", encoding="utf-8")
    args = ["gate", "--catalog", setup["catalog"], "--config", str(plain), "--pipeline", "77"]

    assert main([*args, "--job", f"api={setup['api']}", "--job", f"ui-chrome={setup['ui']}"]) == EXIT_OK
    assert main([*args, "--job", f"api={setup['api']}", "--job", f"ui-chrome={tmp_path}/none"]) == EXIT_INPUT


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--job", "api=x.xml"], "need --pipeline"),
        (["--pipeline", "77"], "at least one --job"),
        (["--pipeline", "77", "--job", "api"], "NAME=PATH"),
        (["--pipeline", "77", "--job", "api=x.xml", "plain.xml"], "give every result input as --job"),
        (["--pipeline", "77", "--job", "api=x.xml", "--attempt", "0"], "at least 1"),
    ],
)
def test_wrong_pipeline_options_are_usage_errors(
    setup: dict[str, str], capsys: pytest.CaptureFixture[str], args: list[str], message: str
) -> None:
    """Exit 2 with a message saying what is wrong."""
    assert main(gate(setup, *args)) == EXIT_USAGE
    assert message in capsys.readouterr().err


def test_history_import_stores_jobs_and_refuses_a_second_import_of_a_job(
    setup: dict[str, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Same files again: fine. Other files for the same job attempt: refused. A re-run: --attempt 2."""
    database = str(tmp_path / "h.db")
    base = ["history", "import", "--database", database, "--pipeline", "77", "--branch", "main"]
    other = junit(tmp_path / "later" / "junit.xml", "api", stamp="2026-10-19T10:00:00")

    assert main([*base, "--job", f"api={setup['api']}", "--job", f"ui-chrome={setup['ui']}"]) == EXIT_OK
    assert main([*base, "--job", f"api={setup['api']}"]) == EXIT_OK  # identical: already stored
    capsys.readouterr()
    assert main([*base, "--job", f"api={other}"]) == EXIT_INPUT
    assert "job api of pipeline 77 (attempt 1) is already imported" in capsys.readouterr().err
    assert main([*base, "--attempt", "2", "--job", f"api={other}"]) == EXIT_OK

    with HistoryStore(database) as store:
        stored = store.runs()
    jobs = sorted((r.pipeline.job, r.pipeline.attempt, r.source) for r in stored if r.pipeline)
    assert jobs == [
        ("api", 1, "api/junit.xml"),
        ("api", 2, "api/junit.xml"),
        ("ui-chrome", 1, "ui-chrome/junit.xml"),
    ]
    assert {r.pipeline.branch for r in stored if r.pipeline} == {"main"}


def test_history_import_still_needs_some_input(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    """No results and no --pipeline: a usage error, not an empty import."""
    assert main(["history", "import", "--database", str(tmp_path / "h.db")]) == EXIT_USAGE
    assert "give result files" in capsys.readouterr().err


def test_a_pipeline_can_name_its_repository(setup: dict[str, str], tmp_path: Path) -> None:
    """--repository is stored with every job; it is invalid without --pipeline or malformed."""
    database = str(tmp_path / "h.db")
    base = ["history", "import", "--database", database, "--pipeline", "77", "--job", f"api={setup['api']}"]

    assert main([*base, "--repository", "niranjankagri/python-pytest-framework"]) == EXIT_OK
    with HistoryStore(database) as store:
        assert {r.pipeline.repository for r in store.runs() if r.pipeline} == {
            "niranjankagri/python-pytest-framework"
        }
    assert main(gate(setup, "--repository", "o/r", setup["api"])) == EXIT_USAGE
