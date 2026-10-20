"""Import many result files at once: files, directories and glob patterns.

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

from qualityintel.ingest.errors import IngestError, NoResultFilesError
from qualityintel.ingest.junit import DEFAULT_ID_PATTERN, read_junit_file
from qualityintel.models.results import RunContext, TestRun

_GLOB_CHARS = re.compile(r"[*?\[]")


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


def expand_inputs(inputs: Iterable[str | Path]) -> tuple[list[Path], list[IngestError]]:
    """Resolve files, directories (all ``*.xml`` below them) and glob patterns to files.

    Patterns are expanded here rather than by the shell, so ``"reports/TEST-*.xml"`` works the
    same in cmd.exe, PowerShell and bash. Each input that matches nothing is an error.
    """
    files: list[Path] = []
    errors: list[IngestError] = []
    for item in inputs:
        text = str(item)
        path = Path(text)
        if _GLOB_CHARS.search(text):
            matches = sorted(Path(p) for p in glob.glob(text, recursive=True) if Path(p).is_file())
        elif path.is_dir():
            matches = sorted(p for p in path.rglob("*.xml") if p.is_file())
        elif path.is_file():
            matches = [path]
        else:
            errors.append(NoResultFilesError(text, "no such file or directory"))
            continue
        if not matches:
            errors.append(NoResultFilesError(text, "matched no result files"))
        files.extend(matches)
    # The same file reached through two inputs is read once
    unique = list(dict.fromkeys(p.resolve() for p in files))
    return unique, errors


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
    for path in files:
        try:
            parsed = read_junit_file(path, context=context, id_pattern=id_pattern)
        except IngestError as error:
            batch.errors.append(error)
            continue
        run = parsed.run
        if run.run_id in seen:
            batch.duplicates.append(f"{path.name} has the same content as {seen[run.run_id]}; skipped")
            continue
        seen[run.run_id] = path.name
        batch.runs.append(run)
        batch.warnings.extend(f"{path.name}: {warning}" for warning in parsed.warnings)
    return batch
