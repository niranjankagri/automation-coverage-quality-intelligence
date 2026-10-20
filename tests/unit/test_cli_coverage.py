from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, EXIT_OK, main

pytestmark = pytest.mark.unit

CATALOG = """
[[requirement]]
id = "R-1"
title = "Checkout"
criticality = "critical"

[[requirement]]
id = "R-2"
title = "Search"

[[test_case]]
id = "TC-1"
title = "Checkout test"
automation_status = "automated"
requirements = ["R-1"]
automated_by = ["c::checkout*"]
"""

RESULTS = '<testsuite name="s"><testcase classname="c" name="checkout works"><failure message="x"/></testcase></testsuite>'


@pytest.fixture
def files(tmp_path: Path) -> tuple[Path, Path]:
    """A catalog and one result file in tmp_path."""
    catalog = tmp_path / "catalog.toml"
    catalog.write_text(CATALOG, encoding="utf-8")
    results = tmp_path / "junit.xml"
    results.write_text(RESULTS, encoding="utf-8")
    return catalog, results


def test_coverage_without_results_shows_catalog_metrics_only(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """No result files: coverage and gaps, execution explicitly not evaluated."""
    catalog, _ = files

    assert main(["coverage", "--catalog", str(catalog)]) == EXIT_OK

    out = capsys.readouterr().out
    assert "requirement coverage            50.0 % (1/2)" in out
    assert "requirements without tests (1): R-2" in out
    assert "EXECUTION" not in out


def test_coverage_with_results_shows_the_failing_critical_requirement(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """The failed checkout test makes critical R-1 failing."""
    catalog, results = files

    assert main(["coverage", "--catalog", str(catalog), str(results)]) == EXIT_OK

    out = capsys.readouterr().out
    assert "failing critical requirements (1): R-1" in out
    assert "execution pass rate             0.0 % (0/1)" in out


def test_filters_narrow_the_scope(files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]) -> None:
    """--criticality critical leaves only R-1."""
    catalog, _ = files

    assert main(["coverage", "--catalog", str(catalog), "--criticality", "critical"]) == EXIT_OK

    assert "requirement coverage            100.0 % (1/1)" in capsys.readouterr().out


def test_broken_catalog_is_an_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A catalog that cannot be loaded stops with exit code 3 and the reason."""
    broken = tmp_path / "catalog.toml"
    broken.write_text("[[requirement]]\nid = ", encoding="utf-8")

    assert main(["coverage", "--catalog", str(broken)]) == EXIT_INPUT
    assert "qi: error: catalog.toml: not valid TOML" in capsys.readouterr().err


def test_missing_results_are_an_input_error(
    files: tuple[Path, Path], capsys: pytest.CaptureFixture[str]
) -> None:
    """Results were asked for but not found: no report is printed."""
    catalog, _ = files

    assert main(["coverage", "--catalog", str(catalog), "nowhere/"]) == EXIT_INPUT

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "nowhere" in captured.err
