"""``qi digest``: the daily digest on the command line, its formats and exit codes."""

from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, EXIT_OK, EXIT_USAGE, main

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[2] / "samples"
BASE = ["digest", "--catalog", str(SAMPLES / "catalog.toml"), str(SAMPLES / "results")]


def test_digest_prints_one_day_with_the_gate(capsys: pytest.CaptureFixture[str]) -> None:
    """Text by default; the gate section appears when a gate is given."""
    code = main([*BASE, "--gate", str(SAMPLES / "gates" / "release.toml"), "--day", "2026-10-13"])

    out = capsys.readouterr().out
    assert code == EXIT_OK
    assert out.startswith("Quality digest 2026-10-13 (compared with 2026-10-12)\n")
    assert "Release gate:\n- release gate: failed" in out


def test_digest_in_markdown_with_absolute_links(capsys: pytest.CaptureFixture[str]) -> None:
    """--markdown and --base-url: links point at the given dashboard."""
    assert main([*BASE, "--markdown", "--base-url", "https://qi.example", "--day", "2026-10-13"]) == EXIT_OK

    out = capsys.readouterr().out
    assert out.startswith("### Quality digest 2026-10-13")
    assert "(https://qi.example/classic/#/runs?since=2026-10-13&until=2026-10-13)" in out


def test_a_day_without_runs_exits_3_and_a_bad_date_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing ran on 1 Oct: notes only, exit 3; '13-10-2026' is not a date: exit 2."""
    assert main([*BASE, "--day", "2026-10-01"]) == EXIT_INPUT
    assert "no dated run in this scope on 2026-10-01" in capsys.readouterr().out
    assert main([*BASE, "--day", "13-10-2026"]) == EXIT_USAGE
    assert "--day must be a date" in capsys.readouterr().err
