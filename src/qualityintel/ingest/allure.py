"""Allure results importer (the ``allure-results`` folder that Allure 2 adapters write).

Supported input (docs/ingestion.md, "Allure"): one folder holding ``*-result.json`` files, one
per test execution, as written by the Allure adapters for TestNG, JUnit 5, pytest and others.
The whole folder is one run. Not a generated Allure *report* (``allure-report/``): that is a web
page whose data layout changes between Allure versions.

Mapping (fields Allure has but this model does not are listed so nothing is misrepresented):

- ``status``: passed / failed / skipped as they are; ``broken`` (an exception outside an
  assertion) becomes ``error``; ``unknown`` becomes ``error`` with a warning, because an
  unknown result must not count as passed or vanish;
- key: ``testClass`` label + ``testMethod`` label (the same key the JUnit XML of TestNG/JUnit
  gives, so history continues across formats), else the ``fullName`` split at its last dot;
  parameters are appended as ``[a, b]``;
- retries: several results with the same ``historyId`` are attempts of one test; the last one
  is the outcome and the earlier ones count as ``retries``;
- explicit test ids: ``AS_ID`` labels and ``tms`` links;
- run context: ``framework`` label; ``browser``, ``environment`` and the build from
  ``environment.properties``; the build is ``build``, else ``git.commit``, else
  ``build.number`` (the code version that was tested, as for the other formats);
- not read: steps, attachments, containers (``*-container.json``, fixtures), categories,
  ``host`` and ``thread`` labels (machine names), ``statusDetails.flaky`` (Allure's own
  judgement; this platform derives flakiness from history).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from qualityintel.ingest.errors import MalformedResultError, UnsupportedFormatError
from qualityintel.ingest.junit import MAX_FILE_BYTES, ParsedFile, merge_context
from qualityintel.models.enums import Outcome
from qualityintel.models.results import MAX_FAILURE_TEXT, FailureDetails, RunContext, TestResult, TestRun

RESULT_SUFFIX = "-result.json"
STATUS = {
    "passed": Outcome.PASSED,
    "failed": Outcome.FAILED,
    "broken": Outcome.ERROR,
    "skipped": Outcome.SKIPPED,
}
# Allow-listed environment.properties keys per field, in order of preference: the build is the
# code version that was tested (as for the other formats); a CI build counter is the fallback
ENVIRONMENT_KEYS = {
    "browser": ("browser",),
    "environment": ("environment",),
    "build": ("build", "git.commit", "build.number"),
}


def is_allure_folder(path: Path) -> bool:
    """True when the folder directly holds Allure result files."""
    return path.is_dir() and any(path.glob(f"*{RESULT_SUFFIX}"))


def read_allure_folder(
    folder: Path, context: RunContext | None = None, source: str | None = None
) -> ParsedFile:
    """Read every ``*-result.json`` of one folder as one run.

    Raises:
        MalformedResultError: A result file is not valid JSON, misses ``name`` or ``status``,
            or the folder is larger than the size limit.
        UnsupportedFormatError: The folder holds no Allure result files.
    """
    name = source or folder.name
    files = sorted(folder.glob(f"*{RESULT_SUFFIX}"))
    if not files:
        raise UnsupportedFormatError(name, f"no *{RESULT_SUFFIX} files: not an Allure results folder")
    if sum(f.stat().st_size for f in files) > MAX_FILE_BYTES:
        raise MalformedResultError(
            name, f"result files are larger than the limit of {MAX_FILE_BYTES} bytes in total"
        )

    digest = hashlib.sha256()
    entries: list[tuple[str, dict[str, Any]]] = []
    for file in files:
        data = file.read_bytes()
        digest.update(file.name.encode() + b"\0" + data)
        try:
            entry = json.loads(data)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise MalformedResultError(name, f"{file.name} is not valid JSON ({error})") from None
        if not isinstance(entry, dict) or not entry.get("name") or not entry.get("status"):
            raise MalformedResultError(name, f"{file.name} has no name or status")
        entries.append((file.name, entry))

    warnings: list[str] = []
    attempts: dict[str, list[dict[str, Any]]] = {}
    for file_name, entry in entries:
        attempts.setdefault(str(entry.get("historyId") or file_name), []).append(entry)
    results = []
    framework = None
    for group in attempts.values():
        group.sort(key=lambda e: int(e.get("stop") or e.get("start") or 0))
        final = group[-1]
        framework = framework or _label(final, "framework")
        results.append(_result(final, retries=len(group) - 1, warnings=warnings))

    file_context = _environment(folder)
    if framework and "framework" not in file_context:
        file_context["framework"] = framework
    starts = [int(e["start"]) for _, e in entries if isinstance(e.get("start"), int)]
    run = TestRun(
        run_id=digest.hexdigest(),
        source=name,
        context=merge_context(RunContext.model_validate(file_context), context),
        started_at=datetime.fromtimestamp(min(starts) / 1000, tz=UTC) if starts else None,
        results=tuple(sorted(results, key=lambda r: r.key)),
    )
    return ParsedFile(run=run, warnings=tuple(warnings))


def _result(entry: Mapping[str, Any], retries: int, warnings: list[str]) -> TestResult:
    """One Allure result as a TestResult."""
    status = str(entry["status"])
    outcome = STATUS.get(status)
    if outcome is None:
        warnings.append(f"{entry['name']}: Allure status {status!r} counted as error")
        outcome = Outcome.ERROR
    classname = _label(entry, "testClass") or ""
    method = _label(entry, "testMethod") or str(entry["name"])
    if not classname:
        full = str(entry.get("fullName") or "")
        classname, _, tail = full.rpartition(".")
        method = tail or method
    parameters = [str(p.get("value", "")) for p in entry.get("parameters") or [] if isinstance(p, dict)]
    if parameters:
        method += f"[{', '.join(parameters)}]"
    start, stop = entry.get("start"), entry.get("stop")
    details = entry.get("statusDetails") or {}
    failure = None
    if outcome is not Outcome.PASSED and (details.get("message") or details.get("trace")):
        failure = FailureDetails(
            message=str(details.get("message") or "").strip(),
            text=str(details.get("trace") or "").strip()[:MAX_FAILURE_TEXT],
        )
    ids = [str(label.get("value")) for label in entry.get("labels") or [] if label.get("name") == "AS_ID"]
    ids += [
        str(link.get("name"))
        for link in entry.get("links") or []
        if link.get("type") == "tms" and link.get("name")
    ]
    return TestResult(
        name=method,
        classname=classname,
        suite=_label(entry, "suite") or "",
        outcome=outcome,
        duration_seconds=(stop - start) / 1000
        if isinstance(start, int) and isinstance(stop, int) and stop >= start
        else None,
        timestamp=datetime.fromtimestamp(start / 1000, tz=UTC) if isinstance(start, int) else None,
        failure=failure,
        test_ids=tuple(dict.fromkeys(ids)),
        retries=retries,
    )


def _label(entry: Mapping[str, Any], name: str) -> str | None:
    """The first label with this name."""
    for label in entry.get("labels") or []:
        if isinstance(label, dict) and label.get("name") == name and label.get("value"):
            return str(label["value"])
    return None


def _environment(folder: Path) -> dict[str, str]:
    """Allow-listed values from Allure's standard environment.properties."""
    path = folder / "environment.properties"
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    raw: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line and not line.lstrip().startswith(("#", "!")):
            key, value = line.split("=", 1)
            raw[key.strip()] = value.strip()
    for field, keys in ENVIRONMENT_KEYS.items():
        found = next((raw[key] for key in keys if raw.get(key)), None)
        if found:
            values[field] = found
    return values
