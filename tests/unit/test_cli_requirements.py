"""`qi requirements import`: preview, apply, re-import, refusal and rollback."""

from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, EXIT_OK, EXIT_USAGE, main
from qualityintel.ingest.catalog_file import load_catalog

pytestmark = pytest.mark.unit

CSV = """id,title,component,criticality
R-1,Checkout works,Checkout,critical
R-2,Search works,Search,medium
"""
CATALOG = """include = ["requirements.toml"]

[[test_case]]
id = "TC-1"
title = "Checkout test"
automation_status = "automated"
requirements = ["R-1"]
automated_by = ["c::checkout*"]
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A folder with the CSV export and a hand-written catalog that includes the generated file."""
    (tmp_path / "export.csv").write_text(CSV, encoding="utf-8")
    (tmp_path / "catalog.toml").write_text(CATALOG, encoding="utf-8")
    return tmp_path


def run(project: Path, *extra: str) -> int:
    """Run the import with the fixture's files."""
    return main(
        [
            "requirements",
            "import",
            str(project / "export.csv"),
            "--into",
            str(project / "requirements.toml"),
            "--catalog",
            str(project / "catalog.toml"),
            *extra,
        ]
    )


def test_preview_writes_nothing(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Without --apply the plan is shown and no file appears."""
    assert run(project) == EXIT_OK

    out = capsys.readouterr().out
    assert "PREVIEW (nothing written; add --apply to write)" in out
    assert "new 2, changed 0, unchanged 0" in out
    assert "+ R-1  Checkout works" in out
    assert not (project / "requirements.toml").exists()


def test_apply_writes_the_file_and_keeps_the_links(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """The catalog then loads with the imported requirements and the hand-written link."""
    assert run(project, "--apply") == EXIT_OK

    catalog = load_catalog(project / "catalog.toml")
    assert [r.id for r in catalog.requirements] == ["R-1", "R-2"]
    assert [(link.requirement_id, link.test_case_id) for link in catalog.links] == [("R-1", "TC-1")]
    assert "catalog.toml loads: 2 requirements, 1 links" in capsys.readouterr().out


def test_second_import_of_the_same_file_changes_nothing(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """No duplicates, and the file is not even rewritten."""
    run(project, "--apply")
    first = (project / "requirements.toml").read_bytes()
    capsys.readouterr()

    assert run(project, "--apply") == EXIT_OK

    out = capsys.readouterr().out
    assert "new 0, changed 0, unchanged 2" in out
    assert "requirements.toml is already up to date" in out
    assert (project / "requirements.toml").read_bytes() == first


def test_changed_csv_updates_in_place_and_names_the_fields(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A changed criticality and a new row: one change, one addition, nothing duplicated."""
    run(project, "--apply")
    (project / "export.csv").write_text(
        CSV.replace("Search,medium", "Search,high") + "R-3,Export works,,low\n", encoding="utf-8"
    )
    capsys.readouterr()

    assert run(project, "--apply") == EXIT_OK

    out = capsys.readouterr().out
    assert "~ R-2  changed: criticality" in out
    assert "+ R-3  Export works" in out
    assert [r.id for r in load_catalog(project / "catalog.toml").requirements] == ["R-1", "R-2", "R-3"]


def test_invalid_rows_stop_the_whole_import(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """All-or-nothing: one bad row, nothing written, every problem listed."""
    (project / "export.csv").write_text(CSV + "R-3,,Export,low\nR-4,Bad,Export,urgent\n", encoding="utf-8")

    assert run(project, "--apply") == EXIT_INPUT

    captured = capsys.readouterr()
    assert "export.csv: row 4, title: is required" in captured.err
    assert "export.csv: row 5, criticality:" in captured.err
    assert "nothing written" in captured.out
    assert not (project / "requirements.toml").exists()


def test_unusable_file_is_an_input_error(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A wrong header stops the import before anything else."""
    (project / "export.csv").write_text("key,summary\nR-1,x\n", encoding="utf-8")

    assert run(project) == EXIT_INPUT
    assert "unknown column(s): key, summary" in capsys.readouterr().err


def test_hand_written_target_is_never_overwritten(project: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """--into the catalog itself is refused; its content stays as it was."""
    target = project / "catalog.toml"

    code = main(["requirements", "import", str(project / "export.csv"), "--into", str(target), "--apply"])

    assert code == EXIT_USAGE
    assert "refusing to overwrite a hand-written file" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == CATALOG


def test_ids_defined_in_the_catalog_itself_are_conflicts(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """R-1 already written by hand in the catalog would become a duplicate: refused."""
    (project / "catalog.toml").write_text(
        CATALOG + '\n[[requirement]]\nid = "R-1"\ntitle = "By hand"\n', encoding="utf-8"
    )

    assert run(project, "--apply") == EXIT_INPUT
    assert "R-1 is already defined in another catalog file" in capsys.readouterr().err
    assert not (project / "requirements.toml").exists()


def test_import_that_would_break_the_catalog_is_rolled_back(
    project: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """A test case linking a requirement that the new file no longer has: old file restored."""
    run(project, "--apply")
    before = (project / "requirements.toml").read_text(encoding="utf-8")
    # A new export written to a fresh target that lacks R-1, used through the same catalog
    (project / "requirements.toml").unlink()
    (project / "export.csv").write_text("id,title\nR-2,Search works\n", encoding="utf-8")
    capsys.readouterr()

    assert run(project, "--apply") == EXIT_INPUT

    assert "the catalog would no longer load, requirements.toml restored" in capsys.readouterr().err
    assert not (project / "requirements.toml").exists()  # there was no file before this import
    assert "R-1" in before
