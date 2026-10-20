"""Import many result files at once: files, directories and glob patterns.

Formats (docs/ingestion.md): JUnit XML (``*.xml``), mochawesome reports (``*.json``, and
``*.html`` when named explicitly) and Allure results folders (a folder with ``*-result.json``
files is one run). A directory input is searched recursively for all of them.

A batch never hides a problem: every file that could not be imported is listed in
``errors``, and a pattern or directory that matched nothing is an error too. The caller
decides what that means (the quality gate treats any error as "results incomplete").
"""

from __future__ import annotations

import glob
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path

from qualityintel.ingest.allure import is_allure_folder, read_allure_folder
from qualityintel.ingest.errors import IngestError, NoResultFilesError, UnsupportedFormatError
from qualityintel.ingest.junit import DEFAULT_ID_PATTERN, ParsedFile, read_junit_file
from qualityintel.ingest.mochawesome import read_mochawesome_file
from qualityintel.models.results import RunContext, TestRun

_GLOB_CHARS = re.compile(r"[*?\[]")
# Files found when a directory is searched (HTML only when named explicitly: report folders
# hold many HTML files that are not results)
_SEARCHED = frozenset({".xml", ".json"})
_READABLE = _SEARCHED | {".html", ".htm"}


@dataclass
class Batch:
    """Outcome of importing several inputs.

    Attributes:
        runs: Successfully imported runs, one per distinct file content.
        duplicates: Files skipped because the same content was already in this batch.
        warnings: Non-fatal remarks, prefixed with the file name.
        errors: Files (or inputs) that could not be imported.
    """

    runs: list[TestRun] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    errors: list[IngestError] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        """True when every input was imported and at least one run came out of it."""
        return not self.errors and bool(self.runs)


def expand_inputs(inputs: Iterable[str | Path]) -> tuple[list[tuple[Path, str]], list[IngestError]]:
    """Resolve files, directories (results below them) and glob patterns to result inputs.

    Patterns are expanded here rather than by the shell, so ``"reports/TEST-*.xml"`` works the
    same in cmd.exe, PowerShell and bash. Each input that matches nothing is an error.

    Returns:
        ``(path, source name)`` pairs and the errors. The source name is the path relative to
        a directory input (``pytest-api/junit.xml``), otherwise the file name, so two files
        called ``junit.xml`` in different folders stay distinguishable.
    """
    files: list[tuple[Path, str]] = []
    errors: list[IngestError] = []
    for item in inputs:
        text = str(item)
        path = Path(text)
        if _GLOB_CHARS.search(text):
            matches = [
                (p, p.name)
                for p in sorted(Path(m) for m in glob.glob(text, recursive=True))
                if p.is_file() or is_allure_folder(p)
            ]
        elif is_allure_folder(path):
            matches = [(path, path.name)]
        elif path.is_dir():
            matches = _search(path)
        elif path.is_file():
            matches = [(path, path.name)]
        else:
            errors.append(NoResultFilesError(text, "no such file or directory"))
            continue
        if not matches:
            errors.append(NoResultFilesError(text, "matched no result files"))
        files.extend(matches)
    # The same file reached through two inputs is read once (first name wins)
    unique: dict[Path, str] = {}
    for file, name in files:
        unique.setdefault(file.resolve(), name)
    return list(unique.items()), errors


def import_results(
    inputs: Iterable[str | Path],
    context: RunContext | None = None,
    id_pattern: re.Pattern[str] = DEFAULT_ID_PATTERN,
) -> Batch:
    """Import every result file the inputs point to.

    Files with identical content (same run id) are imported once; the others are listed in
    ``duplicates``. That catches the common mistake of pointing at a report directory that
    contains the same results twice under different names.
    """
    batch = Batch()
    files, batch.errors = expand_inputs(inputs)
    seen: dict[str, str] = {}
    for path, name in files:
        try:
            parsed = read_any(path, context=context, id_pattern=id_pattern, source=name)
        except IngestError as error:
            batch.errors.append(error)
            continue
        run = parsed.run
        if run.run_id in seen:
            batch.duplicates.append(f"{name} has the same content as {seen[run.run_id]}; skipped")
            continue
        seen[run.run_id] = name
        batch.runs.append(run)
        batch.warnings.extend(f"{name}: {warning}" for warning in parsed.warnings)
    return batch


def read_any(
    path: Path,
    context: RunContext | None = None,
    id_pattern: re.Pattern[str] = DEFAULT_ID_PATTERN,
    source: str | None = None,
) -> ParsedFile:
    """Read one input with the importer its format needs (folder = Allure, else by file suffix)."""
    if is_allure_folder(path):
        return read_allure_folder(path, context=context, source=source)
    suffix = path.suffix.lower()
    if suffix == ".xml":
        return read_junit_file(path, context=context, id_pattern=id_pattern, source=source)
    if suffix in _READABLE:
        return read_mochawesome_file(path, context=context, source=source)
    raise UnsupportedFormatError(
        source or path.name, "unsupported file type (expected .xml, .json, .html or an Allure results folder)"
    )


def _search(root: Path) -> list[tuple[Path, str]]:
    """Result inputs below a directory: Allure folders as a whole, other .xml and .json files."""
    found: list[tuple[Path, str]] = []
    allure: list[Path] = []
    for path in sorted(root.rglob("*")):
        if any(folder in path.parents for folder in allure):
            continue  # inside an Allure folder: its files belong to that run
        if is_allure_folder(path):
            allure.append(path)
            found.append((path, path.relative_to(root).as_posix()))
        elif path.is_file() and path.suffix.lower() in _SEARCHED:
            found.append((path, path.relative_to(root).as_posix()))
    return found
