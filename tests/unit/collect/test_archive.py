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

    with pytest.raises(ArchiveError, match="outside the target folder"):
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


def test_a_file_that_is_not_a_zip_is_refused(tmp_path: Path) -> None:
    """An HTML error page saved as .zip, for example."""
    fake = tmp_path / "a.zip"
    fake.write_text("<html>rate limited</html>", encoding="utf-8")

    with pytest.raises(ArchiveError, match="not a readable zip file"):
        unpack(fake, tmp_path / "out")
