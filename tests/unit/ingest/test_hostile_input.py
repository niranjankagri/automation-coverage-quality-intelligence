"""Broken and hostile result files are input problems (exit 3), never crashes (exit 4).

Each case here was found by probing the importers during the security review (docs/security.md);
before the fix, every one of them either crashed with a Python error or, for the UTF-16 DTD,
had its entities expanded.
"""

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, main
from qualityintel.ingest.allure import read_allure_folder
from qualityintel.ingest.errors import IngestError
from qualityintel.ingest.junit import parse_junit
from qualityintel.ingest.mochawesome import parse_mochawesome

pytestmark = pytest.mark.unit

DTD = (
    '<?xml version="1.0" encoding="{enc}"?><!DOCTYPE t [<!ENTITY a "AAAAAAAAAA">'
    '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">]>'
    '<testsuite name="s"><testcase classname="c" name="&b;"/></testsuite>'
)
DEEP_XML = (
    b"<testsuites>"
    + b"<testsuite name='s'>" * 5000
    + b"<testcase name='t'/>"
    + b"</testsuite>" * 5000
    + b"</testsuites>"
)
DEEP_JSON = b"[" * 100_000 + b"]" * 100_000


def allure(tmp_path: Path, content: object) -> Callable[[], object]:
    """A reader for an Allure folder with one result file holding ``content``."""
    folder = tmp_path / "allure-results"
    folder.mkdir()
    text = content.decode() if isinstance(content, bytes) else json.dumps(content)
    (folder / "x-result.json").write_text(text, encoding="utf-8")
    return lambda: read_allure_folder(folder)


def moch(content: object) -> Callable[[], object]:
    """A parser call on mochawesome content (bytes as they are, anything else as JSON)."""
    data = content if isinstance(content, bytes) else json.dumps(content).encode()
    return lambda: parse_mochawesome(data, "r.json")


@pytest.mark.parametrize(
    ("encoding", "message"),
    [
        ("utf-8", "DTDs and entity declarations"),
        ("utf-16", "DTDs and entity declarations"),
        ("utf-16-be", "cannot be read"),
    ],
)
def test_entities_are_never_expanded_in_any_encoding(encoding: str, message: str) -> None:
    """A byte search for <!DOCTYPE missed UTF-16; the scan now uses the XML parser's own decoding."""
    with pytest.raises(IngestError, match=message):
        parse_junit(DTD.format(enc=encoding.upper()).encode(encoding), "x.xml")


@pytest.mark.parametrize(
    "call",
    [
        pytest.param(lambda _: lambda: parse_junit(DEEP_XML, "x.xml"), id="junit-deep-nesting"),
        pytest.param(lambda _: moch(DEEP_JSON), id="mochawesome-deep-json"),
        pytest.param(
            lambda _: moch(
                {"stats": {}, "results": [{"tests": [{"title": "t", "state": "failed", "err": "boom"}]}]}
            ),
            id="mochawesome-err-is-text",
        ),
        pytest.param(
            lambda _: moch({"stats": {}, "results": [{"tests": {"a": 1}}]}), id="mochawesome-tests-is-object"
        ),
        pytest.param(
            lambda _: moch({"stats": {}, "results": [], "qi_context": [1]}), id="mochawesome-context-is-list"
        ),
        pytest.param(
            lambda tmp: allure(tmp, {"name": "a", "status": "passed", "labels": "x"}),
            id="allure-labels-is-text",
        ),
        pytest.param(
            lambda tmp: allure(tmp, {"name": "a", "status": "passed", "links": ["x"]}),
            id="allure-link-is-text",
        ),
        pytest.param(
            lambda tmp: allure(tmp, {"name": "a", "status": "failed", "statusDetails": "boom"}),
            id="allure-details-is-text",
        ),
        pytest.param(lambda tmp: allure(tmp, DEEP_JSON), id="allure-deep-json"),
    ],
)
def test_unexpected_structure_is_a_malformed_file(
    tmp_path: Path, call: Callable[[Path], Callable[[], object]]
) -> None:
    """Wrong types and absurd nesting name the file instead of raising a Python error."""
    with pytest.raises(IngestError, match=r"nested too deeply|structure is not as expected"):
        call(tmp_path)()


def test_a_hostile_file_is_exit_code_3_through_the_command_line(tmp_path: Path) -> None:
    """Through the CLI the problem is "input invalid", not "internal error"."""
    hostile = tmp_path / "report.json"
    hostile.write_bytes(DEEP_JSON)

    assert main(["inspect", str(hostile)]) == EXIT_INPUT
