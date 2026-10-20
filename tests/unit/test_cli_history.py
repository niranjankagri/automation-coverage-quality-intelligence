from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, EXIT_OK, EXIT_USAGE, main

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[2] / "samples" / "results"


@pytest.fixture
def database(tmp_path: Path) -> Path:
    """A history database filled with every sample run."""
    path = tmp_path / "history.db"
    assert main(["history", "import", str(SAMPLES), "--database", str(path)]) == EXIT_OK
    return path


def test_import_reports_added_and_known_runs(database: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A second import of the same files adds nothing."""
    capsys.readouterr()

    assert main(["history", "import", str(SAMPLES), "--database", str(database)]) == EXIT_OK

    assert "added 0 run(s), 43 already stored" in capsys.readouterr().out


def test_import_uses_qi_database_by_default(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Without --database the QI_DATABASE setting decides the file."""
    target = tmp_path / "from-env.db"
    monkeypatch.setenv("QI_DATABASE", str(target))

    assert main(["history", "import", str(SAMPLES / "pytest-notes-api")]) == EXIT_OK
    assert target.exists()


def test_report_shows_the_real_flaky_candidates(database: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The four tests that passed and failed on the same build are named with their evidence."""
    capsys.readouterr()

    assert main(["history", "report", "--database", str(database)]) == EXIT_OK

    out = capsys.readouterr().out
    assert "4 flaky candidate, 217 stable" in out
    assert "CustomerManagementTest::adminEditsACustomer" in out
    assert "passed and failed on the same build (f5a40d5)" in out
    assert "DURATION REGRESSIONS (2)" in out


def test_report_from_files_only(capsys: pytest.CaptureFixture[str]) -> None:
    """--no-database analyses result files without touching any database."""
    assert (
        main(["history", "report", "--no-database", str(SAMPLES / "playwright-toolshop-firefox")]) == EXIT_OK
    )

    assert "3 flaky candidate, 21 stable" in capsys.readouterr().out


def test_report_filters_runs(database: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--browser chrome keeps only the Robot runs: nothing flaky there."""
    capsys.readouterr()

    assert main(["history", "report", "--database", str(database), "--browser", "chrome"]) == EXIT_OK

    assert "30 stable" in capsys.readouterr().out


def test_report_without_runs_is_an_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """An empty database never produces a clean-looking report."""
    assert main(["history", "report", "--database", str(tmp_path / "empty.db")]) == EXIT_INPUT
    assert "no runs to analyse" in capsys.readouterr().err


def test_bad_window_is_a_usage_error(database: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--window 0 makes no sense."""
    assert main(["history", "report", "--database", str(database), "--window", "0"]) == EXIT_USAGE
    assert "--window must be at least 1" in capsys.readouterr().err


def test_compare_finds_runs_by_file_name(database: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Attempt 1 -> attempt 3 of the same run: the checkout test is fixed."""
    capsys.readouterr()

    code = main(
        [
            "history",
            "compare",
            "39229363499-attempt1.xml",
            "39229363499-attempt3.xml",
            "--database",
            str(database),
        ]
    )

    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "FIXED (1)" in out
    assert "customer can order two products" in out


def test_compare_with_an_ambiguous_reference_is_a_usage_error(
    database: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """'.xml' matches every run; the message asks for more characters."""
    assert main(["history", "compare", ".xml", "attempt3.xml", "--database", str(database)]) == EXIT_USAGE
    assert "43 runs match '.xml'" in capsys.readouterr().err


def test_unusable_database_is_an_input_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A result file passed as the database gives a clear message, not a traceback."""
    not_a_db = tmp_path / "junit.xml"
    not_a_db.write_text("<testsuite/>" * 200, encoding="utf-8")

    assert main(["history", "report", "--database", str(not_a_db)]) == EXIT_INPUT
    assert "cannot be used as a history database" in capsys.readouterr().err


def test_import_of_broken_files_stores_nothing(tmp_path: Path) -> None:
    """Incomplete input is refused as a whole: no partial history."""
    (tmp_path / "good.xml").write_text(
        '<testsuite name="s"><testcase name="t"/></testsuite>', encoding="utf-8"
    )
    (tmp_path / "bad.xml").write_text("<testsuite", encoding="utf-8")

    assert main(["history", "import", str(tmp_path), "--database", str(tmp_path / "h.db")]) == EXIT_INPUT
    assert not (tmp_path / "h.db").exists()
