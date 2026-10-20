from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, EXIT_OK, main

pytestmark = pytest.mark.unit

RESULTS = """<testsuite name="s" timestamp="2026-10-19T10:00:00Z">
  <properties><property name="browser" value="firefox"/></properties>
  <testcase classname="c" name="a"/><testcase classname="c" name="b"/>
  <testcase classname="c" name="c"><failure message="x"/></testcase>
  <testcase classname="c" name="d"><skipped/></testcase>
</testsuite>"""


def test_inspect_prints_one_line_per_run(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Counts, context and the pass rate (skips left out) of each file are shown."""
    (tmp_path / "junit.xml").write_text(RESULTS, encoding="utf-8")

    assert (
        main(["inspect", str(tmp_path), "--context", "framework=pytest", "--context", "build=abc1234"])
        == EXIT_OK
    )

    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("source")
    assert lines[1].split() == [
        "junit.xml",
        "pytest",
        "firefox",
        "abc1234",
        "2",
        "1",
        "0",
        "1",
        "66.7",
        "%",
        "(2/3)",
    ]


def test_inspect_signals_incomplete_input(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A broken file next to a good one: the good one is shown, exit code 3, error on stderr."""
    (tmp_path / "good.xml").write_text(RESULTS, encoding="utf-8")
    (tmp_path / "broken.xml").write_text("<testsuite", encoding="utf-8")

    assert main(["inspect", str(tmp_path)]) == EXIT_INPUT

    captured = capsys.readouterr()
    assert "good.xml" in captured.out
    assert "qi: error: broken.xml: not well-formed XML" in captured.err


def test_inspect_of_nothing_is_an_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """No result files at all is never reported as success."""
    assert main(["inspect", str(tmp_path / "missing")]) == EXIT_INPUT

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "no such file or directory" in captured.err


def test_inspect_shows_notes_for_duplicates_and_warnings(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Duplicates and warnings are notes on stderr; they do not change the exit code."""
    (tmp_path / "a.xml").write_text(RESULTS, encoding="utf-8")
    (tmp_path / "b.xml").write_text(RESULTS, encoding="utf-8")
    (tmp_path / "empty.xml").write_text('<testsuite name="e"/>', encoding="utf-8")

    assert main(["inspect", str(tmp_path)]) == EXIT_OK

    err = capsys.readouterr().err
    assert "qi: note: b.xml has the same content as a.xml; skipped" in err
    assert "qi: note: empty.xml: file contains no test cases" in err


@pytest.mark.parametrize("pair", ["framework", "owner=me", "browser="])
def test_bad_context_option_is_a_usage_error(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], pair: str
) -> None:
    """--context needs NAME=VALUE with a known name and a value."""
    (tmp_path / "junit.xml").write_text(RESULTS, encoding="utf-8")

    assert main(["inspect", str(tmp_path), "--context", pair]) == 2
    assert "--context expects NAME=VALUE" in capsys.readouterr().err
