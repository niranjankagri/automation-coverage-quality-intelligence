"""Reproducible demonstration: every feature on the sample data, from a clean checkout.

Runs the ``qi`` commands a reader of the README would type, in order, each as its own
process (exactly like a pipeline would), and checks that every command returns the exit code
the documentation promises. Reports and the history database go to one output folder.

Usage: ``python tools/demo.py [output folder]`` (default ``demo-output``).
Exit code 0 when every step behaved as documented, 1 otherwise.
"""

from __future__ import annotations

import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).parents[1]


@dataclass(frozen=True)
class Step:
    """One documented command and the exit code it must return."""

    title: str
    arguments: list[str]
    expected_exit: int


def steps(out: Path) -> list[Step]:
    """The demonstration, in reading order."""
    catalog, results, database = "samples/catalog.toml", "samples/results", str(out / "quality.db")
    nightly, release = "samples/gates/nightly.toml", "samples/gates/release.toml"
    attempt1 = "samples/results/playwright-toolshop-firefox/2026-10-19_07f8c24_39229363499-attempt1.xml"
    return [
        Step("1. What do the result files contain?", ["inspect", results], 0),
        Step("2. Coverage, gaps and execution status", ["coverage", "--catalog", catalog, results], 0),
        Step("3. Store the runs in the history", ["history", "import", results, "--database", database], 0),
        Step(
            "4. Importing the same files again adds nothing",
            ["history", "import", results, "--database", database],
            0,
        ),
        Step(
            "5. Stability, recurring failures, slow-downs, trends",
            ["history", "report", "--database", database],
            0,
        ),
        Step(
            "6. What changed between attempt 1 and attempt 3 of the same CI run",
            [
                "history",
                "compare",
                "39229363499-attempt1.xml",
                "39229363499-attempt3.xml",
                "--database",
                database,
            ],
            0,
        ),
        Step(
            "7. Nightly gate on the latest runs: passes",
            ["gate", "--catalog", catalog, "--config", nightly, results, *_reports(out, "nightly")],
            0,
        ),
        Step(
            "8. Release gate: fails on two critical requirements without automation",
            ["gate", "--catalog", catalog, "--config", release, results, *_reports(out, "release")],
            1,
        ),
        Step(
            "9. Nightly gate on the real failed attempt of 19 Oct: fails (critical SHOP-006)",
            ["gate", "--catalog", catalog, "--config", nightly, attempt1, *_reports(out, "nightly-attempt1")],
            1,
        ),
        Step(
            "10. Gate without result files: incomplete, never passed",
            [
                "gate",
                "--catalog",
                catalog,
                "--config",
                nightly,
                str(out / "no-such-results"),
                *_reports(out, "incomplete"),
            ],
            3,
        ),
    ]


def _reports(out: Path, name: str) -> list[str]:
    """Report options writing JSON and HTML into the output folder."""
    return ["--json", str(out / f"{name}.json"), "--html", str(out / f"{name}.html")]


def run(out: Path, show: bool = True) -> list[tuple[Step, int]]:
    """Run every step; returns each step with the exit code it really returned."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "quality.db").unlink(missing_ok=True)  # a fresh history for every demonstration
    outcomes = []
    for step in steps(out):
        command = [sys.executable, "-m", "qualityintel", *step.arguments]
        if show:
            print(f"\n=== {step.title}\n$ qi {' '.join(step.arguments)}", flush=True)
        started = time.monotonic()
        completed = subprocess.run(command, cwd=ROOT, capture_output=not show, text=True, check=False)
        if show:
            verdict = "as documented" if completed.returncode == step.expected_exit else "UNEXPECTED"
            print(
                f"--- exit code {completed.returncode} (expected {step.expected_exit}, {verdict}), "
                f"{time.monotonic() - started:.1f} s",
                flush=True,
            )
        outcomes.append((step, completed.returncode))
    return outcomes


def main(argv: list[str]) -> int:
    """Run the demonstration and summarise it."""
    out = Path(argv[0]).resolve() if argv else ROOT / "demo-output"
    outcomes = run(out)
    wrong = [(step, code) for step, code in outcomes if code != step.expected_exit]
    print(f"\n{len(outcomes) - len(wrong)} of {len(outcomes)} steps behaved as documented; reports in {out}")
    database = out / "quality.db"
    print(f"Dashboard on this data:  qi dashboard --catalog samples/catalog.toml --database {database}")
    for step, code in wrong:
        print(f"UNEXPECTED: {step.title}: exit code {code}, expected {step.expected_exit}", file=sys.stderr)
    return 1 if wrong else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
