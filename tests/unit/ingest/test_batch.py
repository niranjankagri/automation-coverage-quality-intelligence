from pathlib import Path

import pytest

from qualityintel.ingest.batch import expand_inputs, import_results
from qualityintel.ingest.errors import MalformedResultError, NoResultFilesError, UnsupportedFormatError

pytestmark = pytest.mark.unit

GOOD = '<testsuite name="s"><testcase name="{name}"/></testsuite>'


def write(path: Path, content: str) -> Path:
    """Create a file (and its directories) with the given text."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def test_directory_imports_every_xml_file_below_it(tmp_path: Path) -> None:
    """A directory input finds XML files in sub-directories too; other files are ignored."""
    write(tmp_path / "a.xml", GOOD.format(name="a"))
    write(tmp_path / "nested" / "b.xml", GOOD.format(name="b"))
    write(tmp_path / "report.html", "<html/>")

    batch = import_results([tmp_path])

    assert sorted(r.source for r in batch.runs) == ["a.xml", "b.xml"]
    assert batch.complete


def test_glob_pattern_is_expanded_by_the_importer(tmp_path: Path) -> None:
    """Patterns work in cmd.exe too, where the shell does not expand them."""
    write(tmp_path / "TEST-One.xml", GOOD.format(name="one"))
    write(tmp_path / "TEST-Two.xml", GOOD.format(name="two"))
    write(tmp_path / "testng-results.xml", "<testng-results/>")

    batch = import_results([str(tmp_path / "TEST-*.xml")])

    assert sorted(r.source for r in batch.runs) == ["TEST-One.xml", "TEST-Two.xml"]
    assert batch.errors == []


def test_same_content_twice_is_imported_once(tmp_path: Path) -> None:
    """A copy of a result file under another name does not double the counts."""
    write(tmp_path / "junit.xml", GOOD.format(name="t"))
    write(tmp_path / "copy-of-junit.xml", GOOD.format(name="t"))

    batch = import_results([tmp_path])

    assert len(batch.runs) == 1
    assert batch.duplicates == ["junit.xml has the same content as copy-of-junit.xml; skipped"]


def test_same_file_through_two_inputs_is_read_once(tmp_path: Path) -> None:
    """Listing a file and its directory does not count as a duplicate import."""
    path = write(tmp_path / "junit.xml", GOOD.format(name="t"))

    batch = import_results([path, tmp_path])

    assert len(batch.runs) == 1
    assert batch.duplicates == []


def test_bad_file_is_an_error_but_good_files_still_import(tmp_path: Path) -> None:
    """One broken file does not stop the others; the batch is marked incomplete."""
    write(tmp_path / "good.xml", GOOD.format(name="t"))
    write(tmp_path / "broken.xml", "<testsuite><testcase")
    write(tmp_path / "other.xml", "<testng-results/>")

    batch = import_results([tmp_path])

    assert [r.source for r in batch.runs] == ["good.xml"]
    assert sorted(type(e).__name__ for e in batch.errors) == [
        "MalformedResultError",
        "UnsupportedFormatError",
    ]
    assert {e.source for e in batch.errors} == {"broken.xml", "other.xml"}
    assert not batch.complete


@pytest.mark.parametrize("make_input", ["missing", "empty-dir", "no-match"])
def test_inputs_that_match_nothing_are_errors(tmp_path: Path, make_input: str) -> None:
    """A wrong path must never look like "zero tests, nothing failed"."""
    target = {
        "missing": tmp_path / "nope.xml",
        "empty-dir": tmp_path,
        "no-match": tmp_path / "TEST-*.xml",
    }[make_input]

    batch = import_results([target])

    assert batch.runs == []
    assert len(batch.errors) == 1
    assert isinstance(batch.errors[0], NoResultFilesError)
    assert not batch.complete


def test_warnings_are_prefixed_with_the_file_name(tmp_path: Path) -> None:
    """In a batch of many files, each warning says where it comes from."""
    write(tmp_path / "empty.xml", '<testsuite name="s"/>')

    batch = import_results([tmp_path])

    assert batch.warnings == ["empty.xml: file contains no test cases"]


def test_expand_inputs_reports_files_in_a_stable_order(tmp_path: Path) -> None:
    """Sorted file lists keep imports and reports reproducible."""
    for name in ["c.xml", "a.xml", "b.xml"]:
        write(tmp_path / name, GOOD.format(name=name))

    files, errors = expand_inputs([tmp_path])

    assert [f.name for f in files] == ["a.xml", "b.xml", "c.xml"]
    assert errors == []


def test_error_types_are_the_ingest_hierarchy() -> None:
    """All importer errors share one base class, so callers can catch them together."""
    from qualityintel.ingest.errors import IngestError

    for kind in (MalformedResultError, UnsupportedFormatError, NoResultFilesError):
        assert issubclass(kind, IngestError)
