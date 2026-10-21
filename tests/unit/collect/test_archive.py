import stat
import zipfile
from pathlib import Path

import pytest

from qualityintel.collect import archive
from qualityintel.collect.archive import ArchiveError, unpack

pytestmark = pytest.mark.unit


def make_zip(path: Path, members: dict[str, bytes]) -> Path:
    """A zip file with these members."""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as bundle:
        for name, data in members.items():
            bundle.writestr(name, data)
    return path


def test_members_are_unpacked_with_their_folders(tmp_path: Path) -> None:
    """An ordinary artifact: nested folders, files written where they belong."""
    source = make_zip(
        tmp_path / "a.zip", {"junit.xml": b"<testsuite/>", "allure-results/1-result.json": b"{}"}
    )

    written = unpack(source, tmp_path / "out")

    assert sorted(p.relative_to(tmp_path / "out").as_posix() for p in written) == [
        "allure-results/1-result.json",
        "junit.xml",
    ]
    assert (tmp_path / "out" / "junit.xml").read_bytes() == b"<testsuite/>"


@pytest.mark.parametrize(
    "name", ["../evil.txt", "a/../../evil.txt", "/etc/evil", "\\\\server\\x", "C:/evil.txt", "C:evil.txt"]
)
def test_members_that_would_leave_the_folder_are_refused(tmp_path: Path, name: str) -> None:
    """Zip slip: nothing is written outside the target, and nothing at all is written."""
    source = make_zip(tmp_path / "a.zip", {"ok.txt": b"x", name: b"evil"})

    with pytest.raises(ArchiveError, match=r"safe relative path|outside the target folder"):
        unpack(source, tmp_path / "out")
    assert not (tmp_path / "evil.txt").exists()
    assert not (tmp_path / "out" / "ok.txt").exists()  # checked before anything is written


def test_links_are_not_unpacked(tmp_path: Path) -> None:
    """A symbolic link member could point anywhere."""
    source = tmp_path / "a.zip"
    with zipfile.ZipFile(source, "w") as bundle:
        link = zipfile.ZipInfo("link")
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(link, "/etc/passwd")

    with pytest.raises(ArchiveError, match="is a link"):
        unpack(source, tmp_path / "out")


def test_size_and_count_limits(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Too many files or too many bytes (declared, or actually written) are refused."""
    monkeypatch.setattr(archive, "MAX_FILES", 2)
    with pytest.raises(ArchiveError, match="more than the limit of 2"):
        unpack(make_zip(tmp_path / "many.zip", {f"{i}.txt": b"x" for i in range(3)}), tmp_path / "o1")

    monkeypatch.setattr(archive, "MAX_FILES", 5_000)
    monkeypatch.setattr(archive, "MAX_UNPACKED_BYTES", 1000)
    bomb = make_zip(tmp_path / "bomb.zip", {"zeros.bin": b"\0" * 10_000})  # compresses to a few bytes
    with pytest.raises(ArchiveError, match="more than 1000"):
        unpack(bomb, tmp_path / "o2")


def test_duplicate_casefolded_or_conflicting_paths_are_refused_before_writing(tmp_path: Path) -> None:
    """Windows treats these names as the same path or cannot make a file a directory."""
    duplicate = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(duplicate, "w") as bundle:
        bundle.writestr("Report.xml", b"one")
        bundle.writestr("report.xml", b"two")
    with pytest.raises(ArchiveError, match="duplicate member paths"):
        unpack(duplicate, tmp_path / "duplicate-out")

    collision = make_zip(tmp_path / "collision.zip", {"results": b"file", "results/run.xml": b"child"})
    with pytest.raises(ArchiveError, match="conflicting file paths"):
        unpack(collision, tmp_path / "collision-out")
    assert not (tmp_path / "collision-out" / "results").exists()


@pytest.mark.parametrize("name", ["CON.txt", "folder/NUL", "folder/with:stream.xml", "../"])
def test_nonportable_and_unsafe_directory_members_are_refused(tmp_path: Path, name: str) -> None:
    """Every archive entry, including directories, is validated before extraction."""
    source = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(source, "w") as bundle:
        bundle.writestr(name, b"")

    with pytest.raises(ArchiveError):
        unpack(source, tmp_path / "out")


def test_corrupt_member_data_is_reported_as_a_malformed_archive(tmp_path: Path) -> None:
    """CRC/decompression errors become an artifact diagnostic instead of escaping collection."""
    source = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(source, "w", zipfile.ZIP_STORED) as bundle:
        bundle.writestr("junit.xml", b"<testsuite/>")
    content = source.read_bytes()
    source.write_bytes(content.replace(b"<testsuite/>", b"<testsuite!>", 1))

    with pytest.raises(ArchiveError, match="cannot be read"):
        unpack(source, tmp_path / "out")


def test_unpack_refuses_a_nonempty_target_instead_of_reusing_stale_files(tmp_path: Path) -> None:
    """A previous extraction cannot supply a missing file to a later artifact import."""
    target = tmp_path / "out"
    target.mkdir()
    (target / "junit.xml").write_text("stale", encoding="utf-8")

    with pytest.raises(ArchiveError, match="target folder must be new or empty"):
        unpack(make_zip(tmp_path / "valid.zip", {"other.xml": b"<testsuite/>"}), target)

    assert (target / "junit.xml").read_text(encoding="utf-8") == "stale"


def test_a_file_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    """An HTML error page saved as .zip, for example."""
    fake = tmp_path / "a.zip"
    fake.write_text("<html>rate limited</html>", encoding="utf-8")

    with pytest.raises(ArchiveError, match="not a readable zip file"):
        unpack(fake, tmp_path / "out")
