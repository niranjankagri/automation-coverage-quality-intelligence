"""Unpack CI artifacts (zip files from outside) without trusting them.

An artifact is written by another repository's workflow, so it is treated like any other
untrusted input (docs/security.md): a member may not leave the target folder (no absolute
paths, no ``..``, no drive letters), links are not created, and the number of files and the
unpacked size are limited before anything is written. Zip bombs are stopped by the size limit,
which is checked against the sizes the archive declares and again while writing.
"""

from __future__ import annotations

import lzma
import stat
import unicodedata
import zipfile
import zlib
from collections.abc import Callable
from pathlib import Path, PurePosixPath

MAX_FILES = 5_000
MAX_ARCHIVE_ENTRIES = 10_000
MAX_ARCHIVE_BYTES = 150 * 1024 * 1024
MAX_UNPACKED_BYTES = 200 * 1024 * 1024
_CHUNK = 1024 * 1024
_WINDOWS_RESERVED = {
    "con",
    "prn",
    "aux",
    "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}
_INVALID_MEMBER_CHARS = frozenset('<>:"|?*')
_DECOMPRESSION_ERRORS = (
    zipfile.BadZipFile,
    OSError,
    EOFError,
    RuntimeError,
    NotImplementedError,
    zlib.error,
    lzma.LZMAError,
)


class ArchiveError(ValueError):
    """The artifact cannot be unpacked safely."""


def unpack(archive: Path, target: Path, keep: Callable[[str], bool] | None = None) -> list[Path]:
    """Unpack ``archive`` into the (new or empty) folder ``target``; returns the files written.

    ``keep`` chooses members by their ``/``-separated name; the others are not written at all
    (logs, screenshots and attachments a job uploads next to its results). Every member is
    still checked, so an archive with one dangerous member is refused as a whole.

    Raises:
        ArchiveError: Not a zip file, a member that would leave ``target``, a link, ambiguous
            paths, too many files or entries, or more than ``MAX_UNPACKED_BYTES`` unpacked.
    """
    try:
        if archive.stat().st_size > MAX_ARCHIVE_BYTES:
            raise ArchiveError(
                f"{archive.name}: archive is larger than the compressed limit of {MAX_ARCHIVE_BYTES} bytes"
            )
    except OSError as error:
        raise ArchiveError(f"{archive.name}: cannot read archive ({error})") from None
    try:
        bundle = zipfile.ZipFile(archive)
    except (zipfile.BadZipFile, OSError, ValueError, RuntimeError, zipfile.LargeZipFile) as error:
        raise ArchiveError(f"{archive.name}: not a readable zip file ({error})") from None
    with bundle:
        all_members = bundle.infolist()
        if len(all_members) > MAX_ARCHIVE_ENTRIES:
            raise ArchiveError(
                f"{archive.name}: {len(all_members)} entries, more than the limit of {MAX_ARCHIVE_ENTRIES}"
            )
        members = [m for m in all_members if not m.is_dir()]
        if len(members) > MAX_FILES:
            raise ArchiveError(f"{archive.name}: {len(members)} files, more than the limit of {MAX_FILES}")
        declared = sum(m.file_size for m in members)
        if declared > MAX_UNPACKED_BYTES:
            raise ArchiveError(f"{archive.name}: unpacks to {declared} bytes, more than {MAX_UNPACKED_BYTES}")
        root = target.resolve()
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ArchiveError(f"{archive.name}: target folder must be new or empty")
        planned: list[tuple[zipfile.ZipInfo, Path]] = []
        paths: dict[str, str] = {}
        prefixes: set[str] = set()
        for member in all_members:
            destination = _destination(root, member, archive.name)
            if member.is_dir():
                continue
            relative = unicodedata.normalize("NFC", destination.relative_to(root).as_posix()).casefold()
            if relative in paths:
                raise ArchiveError(
                    f"{archive.name}: duplicate member paths {paths[relative]!r} and {member.filename!r}"
                )
            parts = relative.split("/")
            parents = {"/".join(parts[:i]) for i in range(1, len(parts))}
            if any(parent in paths for parent in parents) or relative in prefixes:
                raise ArchiveError(f"{archive.name}: conflicting file paths include {member.filename!r}")
            paths[relative] = member.filename
            prefixes.update("/".join(parts[:i]) for i in range(1, len(parts)))
            if keep is None or keep(member.filename.replace("\\", "/")):
                planned.append((member, destination))
        target.mkdir(parents=True, exist_ok=True)
        written: list[Path] = []
        total = 0
        for member, destination in planned:
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                source = bundle.open(member)
            except _DECOMPRESSION_ERRORS as error:
                raise ArchiveError(
                    f"{archive.name}: member {member.filename!r} cannot be read ({type(error).__name__})"
                ) from None
            with source, destination.open("wb") as sink:
                while True:
                    try:
                        chunk = source.read(_CHUNK)
                    except _DECOMPRESSION_ERRORS as error:
                        raise ArchiveError(
                            f"{archive.name}: member {member.filename!r} cannot be read "
                            f"({type(error).__name__})"
                        ) from None
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_UNPACKED_BYTES:  # the declared sizes were wrong
                        raise ArchiveError(f"{archive.name}: unpacks to more than {MAX_UNPACKED_BYTES} bytes")
                    sink.write(chunk)
            written.append(destination)
    return written


def _destination(root: Path, member: zipfile.ZipInfo, name: str) -> Path:
    """Where a member may be written, or an error if it would escape ``root`` or is a link."""
    filename = (
        member.filename.replace("\\", "/").rstrip("/")
        if member.is_dir()
        else member.filename.replace("\\", "/")
    )
    mode = member.external_attr >> 16
    kind = stat.S_IFMT(mode)
    if kind == stat.S_IFLNK:
        raise ArchiveError(f"{name}: {member.filename!r} is a link; links are not unpacked")
    if kind not in (0, stat.S_IFREG, stat.S_IFDIR):
        raise ArchiveError(f"{name}: {member.filename!r} is a special file; special files are not unpacked")
    parts = PurePosixPath(filename).parts
    raw_parts = filename.split("/")
    unsafe = (
        not parts
        or filename.startswith("/")
        or filename.startswith("//")
        or any(part in ("", ".", "..") for part in raw_parts)
        or any(
            ":" in part
            or part.endswith((".", " "))
            or any(char in _INVALID_MEMBER_CHARS for char in part)
            or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED
            for part in parts
        )
        or any(ord(char) < 32 or ord(char) == 127 for char in filename)
    )
    if unsafe:
        raise ArchiveError(f"{name}: {member.filename!r} is not a safe relative path")
    try:
        destination = root.joinpath(*parts).resolve()
    except (OSError, RuntimeError, ValueError):
        raise ArchiveError(f"{name}: {member.filename!r} is not a usable path") from None
    if not destination.is_relative_to(root):
        raise ArchiveError(f"{name}: {member.filename!r} would be written outside the target folder")
    return destination
