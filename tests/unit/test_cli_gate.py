"""`qi gate` end to end on the sample data: every exit code a pipeline can see."""

import json
from pathlib import Path

import pytest

from qualityintel import cli
from qualityintel.cli import EXIT_GATE_FAILED, EXIT_INPUT, EXIT_INTERNAL, EXIT_OK, EXIT_USAGE, main

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[2] / "samples"
CATALOG = str(SAMPLES / "catalog.toml")
RELEASE = str(SAMPLES / "gates" / "release.toml")
NIGHTLY = str(SAMPLES / "gates" / "nightly.toml")
RESULTS = str(SAMPLES / "results")


def test_release_gate_fails_on_the_uncovered_critical_requirements(tmp_path: Path) -> None:
    """Exit 1; the JSON report names SHOP-008 and ADMIN-012."""
    report = tmp_path / "out" / "gate.json"

    code = main(["gate", "--catalog", CATALOG, "--config", RELEASE, RESULTS, "--json", str(report)])

    assert code == EXIT_GATE_FAILED
    data = json.loads(report.read_text(encoding="utf-8"))
    failed = [r for r in data["rules"] if r["fails_gate"]]
    assert [(r["name"], r["items"]) for r in failed] == [
        ("critical requirements without automation", ["SHOP-008", "ADMIN-012"])
    ]


def test_nightly_gate_passes_on_the_latest_runs(tmp_path: Path) -> None:
    """Exit 0, with HTML and an appended Markdown summary."""
    html, summary = tmp_path / "gate.html", tmp_path / "summary.md"
    summary.write_text("earlier step\n", encoding="utf-8")

    code = main(
        [
            "gate",
            "--catalog",
            CATALOG,
            "--config",
            NIGHTLY,
            RESULTS,
            "--html",
            str(html),
            "--summary",
            str(summary),
        ]
    )

    assert code == EXIT_OK
    assert "nightly gate" in html.read_text(encoding="utf-8")
    text = summary.read_text(encoding="utf-8")
    assert text.startswith("earlier step\n## ✅ nightly gate: PASSED")


def test_nightly_gate_fails_on_the_real_first_attempt(capsys: pytest.CaptureFixture[str]) -> None:
    """19 Oct attempt 1: the checkout test failed, so critical SHOP-006 blocks the gate."""
    attempt1 = str(
        SAMPLES / "results" / "playwright-toolshop-firefox" / "2026-10-19_07f8c24_39229363499-attempt1.xml"
    )

    code = main(["gate", "--catalog", CATALOG, "--config", NIGHTLY, attempt1])

    assert code == EXIT_GATE_FAILED
    assert "SHOP-006" in capsys.readouterr().out


@pytest.mark.parametrize(
    "inputs",
    [[], ["nowhere/"], [RESULTS, "nowhere/"]],
    ids=["no-results", "missing-path", "one-missing-of-two"],
)
def test_missing_results_never_pass(tmp_path: Path, inputs: list[str]) -> None:
    """No files, a wrong path, or one wrong path among good ones: exit 3, report says why."""
    report = tmp_path / "gate.json"

    code = main(["gate", "--catalog", CATALOG, "--config", NIGHTLY, *inputs, "--json", str(report)])

    assert code == EXIT_INPUT
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["gate"]["status"] == "incomplete"
    assert data["input_problems"]


def test_broken_result_file_never_passes(tmp_path: Path) -> None:
    """A truncated JUnit file next to good results: incomplete."""
    (tmp_path / "broken.xml").write_text("<testsuite><testcase name='x'>", encoding="utf-8")

    assert main(["gate", "--catalog", CATALOG, "--config", NIGHTLY, RESULTS, str(tmp_path)]) == EXIT_INPUT


def test_empty_result_file_never_passes(tmp_path: Path) -> None:
    """A suite that crashed before running anything writes an empty suite: incomplete."""
    (tmp_path / "junit.xml").write_text('<testsuite name="s" tests="0"/>', encoding="utf-8")

    assert main(["gate", "--catalog", CATALOG, "--config", NIGHTLY, str(tmp_path)]) == EXIT_INPUT


def test_unreadable_catalog_still_writes_reports(tmp_path: Path) -> None:
    """Exit 3 and an 'incomplete' JSON report, so CI shows why no decision was made."""
    broken = tmp_path / "catalog.toml"
    broken.write_text("[[requirement]]\nid = ", encoding="utf-8")
    report = tmp_path / "gate.json"

    code = main(["gate", "--catalog", str(broken), "--config", NIGHTLY, RESULTS, "--json", str(report)])

    assert code == EXIT_INPUT
    assert json.loads(report.read_text(encoding="utf-8"))["input_problems"][0].startswith(
        "catalog.toml: not valid TOML"
    )


def test_invalid_gate_file_is_a_usage_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """A typo in a threshold name stops the gate with exit 2 instead of skipping the rule."""
    gate = tmp_path / "gate.toml"
    gate.write_text("[execution]\nmin_pass_rat = 95\n", encoding="utf-8")

    assert main(["gate", "--catalog", CATALOG, "--config", str(gate), RESULTS]) == EXIT_USAGE
    assert "min_pass_rat" in capsys.readouterr().err


def test_crash_is_exit_4_not_gate_failed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A bug in qi must never look like a gate decision to the pipeline."""

    def broken(*args: object, **kwargs: object) -> object:
        raise RuntimeError("bug")

    monkeypatch.setattr(cli, "evaluate", broken)

    assert main(["gate", "--catalog", CATALOG, "--config", NIGHTLY, RESULTS]) == EXIT_INTERNAL
    assert "qi: internal error (exit code 4)" in capsys.readouterr().err


def test_scope_in_the_gate_file_limits_the_requirements(tmp_path: Path) -> None:
    """[scope] criticality = critical: 13 requirements in scope."""
    gate = tmp_path / "gate.toml"
    gate.write_text(
        '[coverage]\nmin_requirement_coverage = 0\n[scope]\ncriticality = ["critical"]\n', encoding="utf-8"
    )
    report = tmp_path / "gate.json"

    assert main(["gate", "--catalog", CATALOG, "--config", str(gate), "--json", str(report)]) == EXIT_OK
    assert json.loads(report.read_text(encoding="utf-8"))["inputs"]["requirements_in_scope"] == 13
