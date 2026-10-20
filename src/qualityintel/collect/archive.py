"""Unpack CI artifacts (zip files from outside) without trusting them.

An artifact is written by another repository's workflow, so it is treated like any other
untrusted input (docs/security.md): a member may not leave the target folder (no absolute
paths, no ``..``, no drive letters), links are not created, and the number of files and the
unpacked size are limited before anything is written. Zip bombs are stopped by the size limit,
which is checked against the sizes the archive declares and again while writing.
"""

from __future__ import annotations

import stat
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

MAX_FILES = 5_000
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
_CHUNK = 1024 * 1024


class ArchiveError(ValueError):
    """The artifact cannot be unpacked safely."""


def unpack(archive: Path, target: Path, keep: Callable[[str], bool] | None = None) -> list[Path]:
    """Unpack ``archive`` into the (new or empty) folder ``target``; returns the files written.

    ``keep`` chooses members by their ``/``-separated name; the others are not written at all
    (logs, screenshots and attachments a job uploads next to its results). Every member is
    still checked, so an archive with one dangerous member is refused as a whole.

    Raises:
        ArchiveError: Not a zip file, a member that would leave ``target``, a link, too many
            files, or more than ``MAX_UNPACKED_BYTES`` unpacked.
    """
    try:
        bundle = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError) as error:
        raise ArchiveError(f"{archive.name}: not a readable zip file ({error})") from None
    with bundle:
        members = [m for m in bundle.infolist() if not m.is_dir()]
        if len(members) > MAX_FILES:
            raise ArchiveError(f"{archive.name}: {len(members)} files, more than the limit of {MAX_FILES}")
        declared = sum(m.file_size for m in members)
        if declared > MAX_UNPACKED_BYTES:
            raise ArchiveError(f"{archive.name}: unpacks to {declared} bytes, more than {MAX_UNPACKED_BYTES}")
        target.mkdir(parents=True, exist_ok=True)
        root = target.resolve()
        planned = [
            (member, destination)
            for member in members
            if (destination := _destination(root, member, archive.name))
            and (keep is None or keep(member.filename.replace("\\", "/")))
        ]
        written: list[Path] = []
        total = 0
        for member, destination in planned:
            destination.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, destination.open("wb") as sink:
                while chunk := source.read(_CHUNK):
                    total += len(chunk)
                    if total > MAX_UNPACKED_BYTES:  # the declared sizes were wrong
                        raise ArchiveError(f"{archive.name}: unpacks to more than {MAX_UNPACKED_BYTES} bytes")
                    sink.write(chunk)
            written.append(destination)
    return written


def _destination(root: Path, member: zipfile.ZipInfo, name: str) -> Path:
    """Where a member may be written, or an error if it would escape ``root`` or is a link."""
    if stat.S_ISLNK(member.external_attr >> 16):
        raise ArchiveError(f"{name}: {member.filename} is a link; links are not unpacked")
    parts = PurePosixPath(member.filename.replace("\\", "/")).parts
    if not parts or member.filename.startswith(("/", "\\")) or ".." in parts or ":" in parts[0]:
        raise ArchiveError(f"{name}: {member.filename} would be written outside the target folder")
    destination = root.joinpath(*parts).resolve()
    if not destination.is_relative_to(root):
        raise ArchiveError(f"{name}: {member.filename} would be written outside the target folder")
    return destination
