"""Make a shareable copy of a JUnit XML file.

Used to turn real CI result files into the samples in ``samples/results``. It removes what a
public repository should not contain and what the importer ignores anyway:

- ``<system-out>`` / ``<system-err>`` (test logs),
- ``<properties>`` entries outside an allow-list (Surefire writes every JVM property: class
  paths, home directories, user names),
- ``hostname`` attributes and XML comments.

Optionally it records run context (``--set build=1d03232``) as properties on the top-level
suites, and a start time (``--timestamp 2026-10-13T09:00:00Z``) on top-level suites that have
none (Maven Surefire writes no timestamp), so the copy carries facts that were only known from
the CI run page. ``--overwrite-timestamp`` replaces existing timestamps too; needed for files
made by ``playwright merge-reports``, which stamps suites with the time of the merge, not of
the run.

Test names, outcomes, durations, timestamps and failure messages are kept unchanged, so the
copy imports to exactly the same results as the original (checked by
tests/unit/tools/test_sanitize_junit.py).

Usage::

    python tools/sanitize_junit.py <in.xml> <out.xml> [--set name=value ...]
        [--timestamp ISO [--overwrite-timestamp]]
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from pathlib import Path

DROP_ELEMENTS = frozenset({"system-out", "system-err"})
CONTEXT_NAMES = frozenset({"framework", "browser", "environment", "env", "platform", "build"})
KEEP_PROPERTIES = CONTEXT_NAMES | {"test_id", "test_case_id"}
DROP_ATTRIBUTES = frozenset({"hostname"})


def sanitize(
    data: bytes,
    context: Mapping[str, str] | None = None,
    timestamp: str | None = None,
    overwrite_timestamp: bool = False,
) -> bytes:
    """Return the sanitised XML document as UTF-8 bytes.

    Args:
        data: Original JUnit XML.
        context: Run context to record as properties on every top-level ``<testsuite>``;
            only names from ``CONTEXT_NAMES`` are accepted.
        timestamp: Start time for top-level suites without a ``timestamp`` attribute.
        overwrite_timestamp: Also replace existing timestamps (all suites, nested ones too).
    """
    unknown = set(context or {}) - CONTEXT_NAMES
    if unknown:
        raise ValueError(f"not a context property: {', '.join(sorted(unknown))}")
    # The default parser drops comments, which is what we want
    root = ET.fromstring(data)
    _clean(root)
    top_level = (
        [root] if _local(root.tag) == "testsuite" else [c for c in root if _local(c.tag) == "testsuite"]
    )
    for suite in top_level:
        if context:
            _set_properties(suite, context)
        if timestamp and not suite.get("timestamp"):
            suite.set("timestamp", timestamp)
    if timestamp and overwrite_timestamp:
        for suite in root.iter():
            if _local(suite.tag) == "testsuite":
                suite.set("timestamp", timestamp)
    ET.indent(root, space="  ")
    document: bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return document + b"\n"


def _clean(element: ET.Element) -> None:
    """Remove logs, unknown properties and host names below ``element`` (in place)."""
    for name in DROP_ATTRIBUTES:
        element.attrib.pop(name, None)
    for child in list(element):
        tag = _local(child.tag)
        if tag in DROP_ELEMENTS:
            element.remove(child)
        elif tag == "properties":
            for prop in list(child):
                if prop.get("name", "").lower() not in KEEP_PROPERTIES:
                    child.remove(prop)
            if len(child) == 0:
                element.remove(child)
        else:
            _clean(child)


def _set_properties(suite: ET.Element, context: Mapping[str, str]) -> None:
    """Add or replace context properties in the suite's own ``<properties>`` block."""
    block = next((c for c in suite if _local(c.tag) == "properties"), None)
    if block is None:
        block = ET.Element("properties")
        suite.insert(0, block)
    for prop in list(block):
        if prop.get("name") in context:
            block.remove(prop)
    for name, value in context.items():
        ET.SubElement(block, "property", {"name": name, "value": value})


def _local(tag: str) -> str:
    """Element name without namespace."""
    return tag.rsplit("}", 1)[-1]


def main(argv: list[str]) -> int:
    """Command line entry: sanitise one file into another (exit code 2 on wrong usage)."""
    parser = argparse.ArgumentParser(prog="sanitize_junit.py", description="Make a shareable JUnit XML copy.")
    parser.add_argument("source", type=Path)
    parser.add_argument("target", type=Path)
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE", help="record run context")
    parser.add_argument("--timestamp", help="start time for suites that have none (ISO 8601)")
    parser.add_argument("--overwrite-timestamp", action="store_true", help="replace existing timestamps too")
    try:
        args = parser.parse_args(argv)
    except SystemExit as stop:
        return int(stop.code or 0)
    if not all("=" in pair for pair in args.set):
        parser.print_usage(sys.stderr)
        print("--set needs NAME=VALUE", file=sys.stderr)
        return 2
    context = dict(pair.split("=", 1) for pair in args.set)
    args.target.parent.mkdir(parents=True, exist_ok=True)
    args.target.write_bytes(
        sanitize(args.source.read_bytes(), context, args.timestamp, args.overwrite_timestamp)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
