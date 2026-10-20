"""Acceptance criterion 9: a clean checkout reproduces the documented demonstration."""

import json
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
import demo  # noqa: E402


def test_every_demonstration_step_returns_its_documented_exit_code(tmp_path: Path) -> None:
    """Eleven steps, each a separate `python -m qualityintel` process, each with the expected code."""
    outcomes = demo.run(tmp_path, show=False)

    assert [(step.title, code) for step, code in outcomes] == [
        (step.title, step.expected_exit) for step, _ in outcomes
    ]
    assert len(outcomes) == 11


def test_demonstration_writes_its_reports_and_history(tmp_path: Path) -> None:
    """The output folder holds the history database and a JSON + HTML report per gate."""
    demo.run(tmp_path, show=False)

    assert (tmp_path / "quality.db").stat().st_size > 0
    for name in ("nightly", "release", "nightly-attempt1", "incomplete"):
        assert (tmp_path / f"{name}.html").exists()
    statuses = {
        name: json.loads((tmp_path / f"{name}.json").read_text(encoding="utf-8"))["gate"]["status"]
        for name in ("nightly", "release", "nightly-attempt1", "incomplete")
    }
    assert statuses == {
        "nightly": "passed",
        "release": "failed",
        "nightly-attempt1": "failed",
        "incomplete": "incomplete",
    }


def test_main_reports_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The command line entry ends with the summary line and exit code 0."""
    assert demo.main([str(tmp_path)]) == 0

    assert "11 of 11 steps behaved as documented" in capsys.readouterr().out
