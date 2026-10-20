"""``qi collect`` and ``qi gate --database`` with the fake CI source."""

import json
import re
from pathlib import Path
from typing import Any

import pytest

from qualityintel import cli
from qualityintel.cli import EXIT_GATE_FAILED, EXIT_INPUT, EXIT_OK, EXIT_USAGE, main
from qualityintel.collect.github import CollectError, WorkflowRun

from .test_collector import FakeSource, good_artifacts, run

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[3] / "samples"
PRODUCERS = """
[[producer]]
repository = "niranjankagri/python-pytest-framework"
workflow = "ci.yml"
context = { framework = "pytest", environment = "ci" }
[[producer.job]]
name = "api"
artifact = "report-api"
path = "junit.xml"
[[producer.job]]
name = "ui"
artifact = "report-ui"
path = "reports/junit.xml"
context = { browser = "chromium" }
"""
GATE = '[execution]\nmax_failed_tests = 0\n[pipeline]\njobs = ["api", "ui"]\n'


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Producers file, gate file, token in the environment, and a fake source the CLI uses."""
    (tmp_path / "producers.toml").write_text(PRODUCERS, encoding="utf-8")
    (tmp_path / "gate.toml").write_text(GATE, encoding="utf-8")
    monkeypatch.setenv("GITHUB_TOKEN", "ghs_test_token")
    holder: dict[str, Any] = {"source": FakeSource([run()], good_artifacts()), "dir": tmp_path}
    monkeypatch.setattr(cli, "GitHubActions", lambda token: holder["source"])
    holder["base"] = [
        "collect",
        "--producers",
        str(tmp_path / "producers.toml"),
        "--database",
        str(tmp_path / "h.db"),
    ]
    return holder


def gate(setup: dict[str, Any], pipeline: str) -> list[str]:
    """``qi gate`` on a collected pipeline."""
    d = setup["dir"]
    return [
        "gate", "--catalog", str(SAMPLES / "catalog.toml"), "--config", str(d / "gate.toml"),
        "--database", str(d / "h.db"), "--pipeline", pipeline, "--json", str(d / "gate.json"),
    ]  # fmt: skip


def test_collect_prints_and_writes_the_audit(
    setup: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Exit 0; the audit counts the pipeline; the Markdown summary is appended."""
    summary = setup["dir"] / "summary.md"

    assert main([*setup["base"], "--summary", str(summary)]) == EXIT_OK

    out = capsys.readouterr().out
    assert "1 completed run(s), 1 collected, 0 collected before" in out
    assert "niranjankagri/python-pytest-framework" in out
    assert "| niranjankagri/python-pytest-framework | 1 | 1 | 0 | 46 |" in summary.read_text(encoding="utf-8")


def test_a_complete_collected_pipeline_passes_the_gate(setup: dict[str, Any]) -> None:
    """Acceptance: a new CI run is in history without copying reports, and can be gated."""
    main(setup["base"])

    assert main(gate(setup, "python-pytest-framework#100")) == EXIT_OK


def test_a_cancelled_pipeline_with_a_missing_job_never_passes(setup: dict[str, Any]) -> None:
    """The UI job's report is missing: the gate is incomplete although the API results pass."""
    artifacts = good_artifacts()
    del artifacts["report-ui"]
    setup["source"] = FakeSource([run(conclusion="cancelled")], artifacts)
    main(setup["base"])

    assert main(gate(setup, "python-pytest-framework#100")) == EXIT_INPUT
    problems = json.loads((setup["dir"] / "gate.json").read_text(encoding="utf-8"))["input_problems"]
    assert any("artifact report-ui not found" in p for p in problems)


def test_an_unknown_pipeline_is_incomplete_not_passed(setup: dict[str, Any]) -> None:
    """Nothing collected under that id: no decision."""
    main(setup["base"])

    assert main(gate(setup, "python-pytest-framework#999")) == EXIT_INPUT


def test_a_failing_test_in_a_collected_pipeline_fails_the_gate(setup: dict[str, Any]) -> None:
    """Complete, but a failure in the report: exit 1."""
    artifacts = good_artifacts()
    api = artifacts["report-api"]
    assert isinstance(api, dict)
    # The first testcase gets a failure (the sample writes them self-closing)
    failing = rb"\1><failure message='boom'/></testcase>"
    api["junit.xml"] = re.sub(rb"(<testcase[^>]*?)/>", failing, api["junit.xml"], count=1)
    setup["source"] = FakeSource([run()], artifacts)
    main(setup["base"])

    assert main(gate(setup, "python-pytest-framework#100")) == EXIT_GATE_FAILED


def test_collect_errors_are_exit_3_and_shown(
    setup: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """A producer that cannot be read is an input problem; nothing was recorded for it."""
    setup["source"].fail_listing = CollectError("HTTP 403 (forbidden or rate limited)", transient=True)

    assert main(setup["base"]) == EXIT_INPUT
    assert "ERROR niranjankagri/python-pytest-framework: HTTP 403" in capsys.readouterr().out


def test_usage_errors(
    setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """No token, bad --days, a broken producers file, --database without --pipeline: exit 2."""
    assert main([*setup["base"], "--days", "0"]) == EXIT_USAGE
    (setup["dir"] / "bad.toml").write_text("[[producer]]\nrepository = 1\n", encoding="utf-8")
    assert main(["collect", "--producers", str(setup["dir"] / "bad.toml")]) == EXIT_USAGE
    assert main([*gate(setup, "x")[:-4], "--database", str(setup["dir"] / "h.db")]) == EXIT_USAGE
    monkeypatch.delenv("GITHUB_TOKEN")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert main(setup["base"]) == EXIT_USAGE
    assert "set GITHUB_TOKEN" in capsys.readouterr().err


def test_audit_only_needs_no_token_and_downloads_nothing(
    setup: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The audit is read from the database."""
    main(setup["base"])
    monkeypatch.delenv("GITHUB_TOKEN")
    setup["source"] = FakeSource([WorkflowRun(1, 1, 1, "push", "main", "x", "success", "", None)], {})

    assert main([*setup["base"], "--audit-only"]) == EXIT_OK
    assert setup["source"].downloads == 0
