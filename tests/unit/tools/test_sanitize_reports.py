import json
import sys
from pathlib import Path

import pytest

from qualityintel.ingest.allure import read_allure_folder
from qualityintel.ingest.mochawesome import parse_mochawesome
from qualityintel.ingest.playwright_json import parse_playwright

sys.path.insert(0, str(Path(__file__).parents[3] / "tools"))
from sanitize_reports import main, sanitize_allure, sanitize_mochawesome, sanitize_playwright

pytestmark = pytest.mark.unit

REPORT = {
    "stats": {"start": "2026-10-19T10:00:00Z", "tests": 1},
    "results": [
        {
            "fullFile": "a.cy.ts",
            "tests": [],
            "suites": [
                {
                    "title": "S",
                    "suites": [],
                    "tests": [
                        {
                            "title": "t",
                            "state": "failed",
                            "duration": 10,
                            "code": "cy.type('secret-password')",
                            "context": "data:image/png;base64,AAAA",
                            "err": {"message": "boom", "estack": r"at C:\Users\someone\x.ts:1"},
                        }
                    ],
                }
            ],
        }
    ],
}


def test_mochawesome_copy_drops_code_and_screenshots_but_keeps_results() -> None:
    """Same results after cleaning; no test source, no embedded screenshots, no local paths."""
    cleaned = sanitize_mochawesome(
        json.dumps(REPORT).encode(), html_report=False, context={"browser": "chrome"}
    )
    text = json.dumps(cleaned)

    assert "secret-password" not in text
    assert "base64" not in text
    assert "someone" not in text
    before = parse_mochawesome(json.dumps(REPORT).encode(), "r.json").run.results[0]
    after = parse_mochawesome(text.encode(), "r.json").run
    assert (after.results[0].key, after.results[0].outcome) == (before.key, before.outcome)
    assert after.context.browser == "chrome"


def test_mochawesome_context_names_are_checked() -> None:
    """Only run-context names can be recorded."""
    with pytest.raises(ValueError, match="not a context property: owner"):
        sanitize_mochawesome(json.dumps(REPORT).encode(), html_report=False, context={"owner": "x"})


def test_allure_copy_keeps_results_and_drops_the_rest(tmp_path: Path) -> None:
    """Results stay importable; attachments, containers, steps and host labels are gone."""
    source = tmp_path / "allure-results"
    source.mkdir()
    entry = {
        "name": "a",
        "status": "passed",
        "fullName": "c.A.a",
        "steps": [{"name": "login with password=hunter2"}],
        "labels": [{"name": "host", "value": "build-agent-7"}, {"name": "testClass", "value": "c.A"}],
    }
    (source / "1-result.json").write_text(json.dumps(entry), encoding="utf-8")
    (source / "2-attachment.txt").write_text("token=abc", encoding="utf-8")
    (source / "environment.properties").write_text("browser=chrome\ndatabase=jdbc:secret\n", encoding="utf-8")
    target = tmp_path / "clean"

    assert sanitize_allure(source, target) == 1

    copied = "".join(p.read_text(encoding="utf-8") for p in target.iterdir())
    assert sorted(p.name for p in target.iterdir()) == ["1-result.json", "environment.properties"]
    for secret in ("hunter2", "build-agent-7", "token=abc", "jdbc:secret"):
        assert secret not in copied
    assert read_allure_folder(target).run.results[0].key == "c.A::a"


def test_command_line(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Both sub-commands work; --set needs NAME=VALUE."""
    report = tmp_path / "r.json"
    report.write_text(json.dumps(REPORT), encoding="utf-8")

    assert main(["mochawesome", str(report), str(tmp_path / "out.json"), "--set", "build=abc"]) == 0
    assert json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))["qi_context"] == {"build": "abc"}
    assert main(["mochawesome", str(report), str(tmp_path / "x.json"), "--set", "build"]) == 2
    assert main([]) == 2


def test_playwright_copy_drops_logs_attachments_and_paths_but_keeps_results() -> None:
    """Every attempt keeps status, retry and error; logs, attachments and local paths go."""
    report = {
        "config": {
            "version": "1.64.0",
            "rootDir": "/home/someone/project",
            "projects": [{"name": "chromium", "outputDir": "x"}],
        },
        "suites": [
            {
                "title": "a.spec.ts",
                "file": "a.spec.ts",
                "specs": [
                    {
                        "title": "t",
                        "file": "a.spec.ts",
                        "tests": [
                            {
                                "projectName": "chromium",
                                "results": [
                                    {
                                        "status": "failed",
                                        "retry": 0,
                                        "duration": 5,
                                        "stdout": [{"text": "token=abc"}],
                                        "attachments": [{"name": "trace", "path": "/home/someone/trace.zip"}],
                                        "errors": [
                                            {"message": "boom", "stack": r"at C:\Users\someone\a.spec.ts:1"}
                                        ],
                                    },
                                    {"status": "passed", "retry": 1, "duration": 4, "errors": []},
                                ],
                            }
                        ],
                    }
                ],
            }
        ],
        "errors": [],
        "stats": {"startTime": "2026-10-26T06:32:26Z"},
    }
    cleaned = sanitize_playwright(json.dumps(report).encode())
    first, second = cleaned["suites"][0]["specs"][0]["tests"][0]["results"]

    assert cleaned["config"] == {"version": "1.64.0", "projects": [{"name": "chromium"}]}
    assert "stdout" not in first
    assert "attachments" not in first
    assert "someone" not in json.dumps(cleaned)
    assert (first["status"], first["retry"], second["status"], second["retry"]) == ("failed", 0, "passed", 1)
    assert parse_playwright(json.dumps(cleaned).encode(), "x.json").run.results[0].retries == 1
