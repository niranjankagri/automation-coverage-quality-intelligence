"""Make shareable copies of mochawesome, Playwright JSON and Allure results (the samples).

Like tools/sanitize_junit.py, it removes what a public repository should not hold and what the
importers do not read anyway, and keeps everything they do read unchanged:

- mochawesome: the JSON is taken from the HTML report's ``data-raw`` attribute when needed;
  each test loses ``code`` (its source) and ``context`` (embedded screenshots and values);
  failure messages lose local paths; run context can be recorded as ``qi_context``.
- Allure: only ``*-result.json`` files and an allow-listed ``environment.properties`` are copied
  (no attachments, containers, executor or categories files); each result loses ``steps``,
  ``attachments``, ``description`` and the ``host``/``thread`` labels.
- Playwright JSON: ``config`` keeps only the version and the project names (paths, argv,
  CI metadata go); every attempt loses ``stdout``, ``stderr``, ``attachments``, ``steps`` and
  ``annotations``; error messages and stacks lose local paths.

Usage::

    python tools/sanitize_reports.py mochawesome <report.html|json> <out.json> [--set name=value ...]
    python tools/sanitize_reports.py allure <allure-results folder> <out folder>
    python tools/sanitize_reports.py playwright <results.json> <out.json>
"""

from __future__ import annotations

import argparse
import html
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

from sanitize_junit import CONTEXT_NAMES, LOCAL_PATH, LOCAL_PATH_MARK

DATA_RAW = re.compile(rb'data-raw="([^"]*)"')
DROPPED_TEST_KEYS = frozenset({"code", "context"})
DROPPED_RESULT_KEYS = frozenset({"steps", "attachments", "description", "descriptionHtml"})
DROPPED_LABELS = frozenset({"host", "thread"})
ENVIRONMENT_KEYS = ("browser", "environment", "build", "build.number", "git.commit")
DROPPED_ATTEMPT_KEYS = frozenset({"stdout", "stderr", "attachments", "steps", "annotations"})


def sanitize_mochawesome(
    data: bytes, html_report: bool, context: dict[str, str] | None = None
) -> dict[str, Any]:
    """The cleaned mochawesome report as a dict."""
    unknown = set(context or {}) - CONTEXT_NAMES
    if unknown:
        raise ValueError(f"not a context property: {', '.join(sorted(unknown))}")
    if html_report:
        found = DATA_RAW.search(data)
        if found is None:
            raise ValueError("no mochawesome data-raw attribute in this HTML file")
        data = html.unescape(found.group(1).decode("utf-8")).encode()
    report: dict[str, Any] = json.loads(data)

    def clean(suite: dict[str, Any]) -> None:
        for test in suite.get("tests") or []:
            for key in DROPPED_TEST_KEYS:
                test.pop(key, None)
            err = test.get("err") or {}
            for key in ("message", "estack", "diff"):
                if isinstance(err.get(key), str):
                    err[key] = LOCAL_PATH.sub(LOCAL_PATH_MARK, err[key])
        for child in suite.get("suites") or []:
            clean(child)

    for root in report.get("results") or []:
        clean(root)
    if context:
        report["qi_context"] = dict(context)
    return report


def sanitize_allure(source: Path, target: Path) -> int:
    """Copy the cleaned results of one Allure folder; returns the number of results."""
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    count = 0
    for file in sorted(source.glob("*-result.json")):
        result = json.loads(file.read_bytes())
        for key in DROPPED_RESULT_KEYS:
            result.pop(key, None)
        result["labels"] = [
            label for label in result.get("labels") or [] if label.get("name") not in DROPPED_LABELS
        ]
        details = result.get("statusDetails") or {}
        for key in ("message", "trace"):
            if isinstance(details.get(key), str):
                details[key] = LOCAL_PATH.sub(LOCAL_PATH_MARK, details[key])
        (target / file.name).write_text(
            json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        count += 1
    environment = source / "environment.properties"
    if environment.is_file():
        kept = [
            line
            for line in environment.read_text(encoding="utf-8").splitlines()
            if "=" in line and line.split("=", 1)[0].strip() in ENVIRONMENT_KEYS
        ]
        (target / "environment.properties").write_text("\n".join(kept) + "\n", encoding="utf-8", newline="\n")
    return count


def sanitize_playwright(data: bytes) -> dict[str, Any]:
    """The cleaned Playwright JSON report as a dict."""
    report: dict[str, Any] = json.loads(data)
    config = report.get("config") or {}
    report["config"] = {
        "version": config.get("version"),
        "projects": [{"name": project.get("name")} for project in config.get("projects") or []],
    }

    def clean_error(error: dict[str, Any]) -> None:
        for key in ("message", "stack", "snippet"):
            if isinstance(error.get(key), str):
                error[key] = LOCAL_PATH.sub(LOCAL_PATH_MARK, error[key])
        error.pop("location", None)

    def clean(suite: dict[str, Any]) -> None:
        for spec in suite.get("specs") or []:
            for test in spec.get("tests") or []:
                for attempt in test.get("results") or []:
                    for key in DROPPED_ATTEMPT_KEYS:
                        attempt.pop(key, None)
                    for error in [attempt.get("error") or {}, *(attempt.get("errors") or [])]:
                        clean_error(error)
        for child in suite.get("suites") or []:
            clean(child)

    for root in report.get("suites") or []:
        clean(root)
    for error in report.get("errors") or []:
        clean_error(error)
    return report


def main(argv: list[str]) -> int:
    """Command line entry (exit code 2 on wrong usage)."""
    parser = argparse.ArgumentParser(prog="sanitize_reports.py")
    kinds = parser.add_subparsers(dest="kind", required=True)
    moch = kinds.add_parser("mochawesome")
    moch.add_argument("source", type=Path)
    moch.add_argument("target", type=Path)
    moch.add_argument("--set", action="append", default=[], metavar="NAME=VALUE")
    allure = kinds.add_parser("allure")
    allure.add_argument("source", type=Path)
    allure.add_argument("target", type=Path)
    playwright = kinds.add_parser("playwright")
    playwright.add_argument("source", type=Path)
    playwright.add_argument("target", type=Path)
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return int(stop.code or 0)
    if args.kind == "allure":
        print(f"{sanitize_allure(args.source, args.target)} results copied")
        return 0
    if args.kind == "playwright":
        args.target.parent.mkdir(parents=True, exist_ok=True)
        cleaned = sanitize_playwright(args.source.read_bytes())
        args.target.write_text(
            json.dumps(cleaned, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
        )
        return 0
    if not all("=" in pair for pair in args.set):
        print("--set needs NAME=VALUE", file=sys.stderr)
        return 2
    report = sanitize_mochawesome(
        args.source.read_bytes(),
        args.source.suffix.lower() in {".html", ".htm"},
        dict(p.split("=", 1) for p in args.set),
    )
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
