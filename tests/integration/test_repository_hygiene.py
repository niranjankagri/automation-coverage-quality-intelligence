"""Nothing sensitive is published: checked on every file git tracks, on every CI run.

The project plan requires that no credentials, employer code, customer data or internal reports
are published. This test turns that into rules a machine can check. Test files are excluded on
purpose: they contain fake secrets (``hunter2``) to prove that the sanitiser removes them.
"""

import json
import re
import subprocess
import xml.etree.ElementTree as ET
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2]

SECRETS = {
    "GitHub token": re.compile(r"\b(ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}"),
    "AWS access key": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "private key": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    "Slack token": re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"),
    "API key": re.compile(r"\bsk-(ant-)?[A-Za-z0-9_-]{24,}"),
    "password value": re.compile(r"(?i)\bpassword\s*[=:]\s*['\"][^'\"\s]{4,}['\"]"),
}
PRIVATE_PATHS = {
    # a real name after Users\ (documentation placeholders such as Users\<name>\ are fine)
    "Windows user folder": re.compile(r"(?i)\b[a-z]:[\\/]+users[\\/]+(?!<)"),
    "home folder (other than CI's runner)": re.compile(r"/home/(?!runner\b)[a-z][a-z0-9_-]*/"),
    "local user or machine name": re.compile(r"\bniran\b|\bMSI\b"),
    "personal e-mail": re.compile(r"(?i)[a-z0-9._%+-]+@(gmail|yahoo|outlook|hotmail)\.com"),
}
# Former employers and their clients are never named in this public repository
EMPLOYERS = re.compile(r"(?i)\b(sycamore|ephicacy|bebo|mivo|telekom|check24|qasource|nocell|trepp|e\.on)\b")


def tracked_text_files() -> list[Path]:
    """Every text file git tracks, except tests (which hold fake secrets on purpose)."""
    names = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.splitlines()
    files = [ROOT / name for name in names if not name.startswith("tests/")]
    return [path for path in files if path.suffix.lower() not in {".png", ".jpg", ".ico"} and path.is_file()]


FILES = tracked_text_files()


def test_files_are_found() -> None:
    """Guard: a broken git call must not make every rule below pass on zero files."""
    assert len(FILES) > 50


@pytest.mark.parametrize(
    ("label", "pattern"), [*SECRETS.items(), *PRIVATE_PATHS.items(), ("employer or client name", EMPLOYERS)]
)
def test_no_tracked_file_contains(label: str, pattern: re.Pattern[str]) -> None:
    """Secrets, private paths, personal data and employer names appear nowhere."""
    hits = []
    for path in FILES:
        text = path.read_text(encoding="utf-8", errors="replace")
        for number, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                hits.append(f"{path.relative_to(ROOT).as_posix()}:{number}")
    assert not hits, f"{label} found in: {', '.join(hits[:10])}"


@pytest.mark.parametrize("path", sorted((ROOT / "samples" / "results").rglob("*.xml")), ids=lambda p: p.name)
def test_sample_results_stay_sanitised(path: Path) -> None:
    """No logs, no host names, only allow-listed properties in the committed result files."""
    root = ET.parse(path).getroot()
    allowed = {"framework", "browser", "environment", "env", "platform", "build", "test_id", "test_case_id"}

    assert not [e for e in root.iter() if e.tag in {"system-out", "system-err"}]
    assert all("hostname" not in e.attrib for e in root.iter())
    assert {p.get("name") for p in root.iter("property")} <= allowed


def test_the_rules_catch_what_they_should() -> None:
    """Each rule matches a planted example, so a green run means something."""
    planted = {
        "GitHub token": "token ghp_" + "a" * 36,
        "AWS access key": "AKIA" + "ABCDEFGHIJKLMNOP",
        "private key": "-----BEGIN RSA PRIVATE KEY-----",
        "Slack token": "xoxb-" + "1234567890-abc",
        "API key": "sk-ant-" + "x" * 30,
        "password value": 'password = "hunter2x"',
        "Windows user folder": r"C:\Users\someone\file",
        "home folder (other than CI's runner)": "/home/someone/project",
        "local user or machine name": "built on MSI",
        "personal e-mail": "someone@gmail.com",
    }
    for label, example in planted.items():
        assert {**SECRETS, **PRIVATE_PATHS}[label].search(example), label
    assert not PRIVATE_PATHS["home folder (other than CI's runner)"].search("/home/runner/work/x/")
    assert EMPLOYERS.search("worked at Sycamore")


FORMATS = ROOT / "samples" / "formats"


@pytest.mark.parametrize(
    "path", sorted(FORMATS.glob("cypress-*/*.json")), ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_cypress_samples_carry_no_test_code_or_screenshots(path: Path) -> None:
    """Mochawesome copies keep results only: no test 'code', no 'context' (embedded screenshots)."""
    text = path.read_text(encoding="utf-8")

    def tests(suite: dict[str, Any]) -> Iterator[dict[str, Any]]:
        yield from suite.get("tests") or []
        for child in suite.get("suites") or []:
            yield from tests(child)

    found = [t for root in json.loads(text)["results"] for t in tests(root)]
    assert found
    assert not any("code" in t or "context" in t for t in found)
    assert "base64" not in text


def test_allure_samples_hold_results_and_environment_only() -> None:
    """No attachments, containers, executor files, steps or machine labels in the Allure copies."""
    files = [p for p in (FORMATS / "allure-enterprise-api").rglob("*") if p.is_file()]

    assert files
    assert {p.name for p in files if not p.name.endswith("-result.json")} == {"environment.properties"}
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert '"steps"' not in text
        assert '"host"' not in text
        assert '"thread"' not in text
