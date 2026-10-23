"""Take the dashboard and gate-report screenshots used in the docs (docs/images).

Starts the dashboard on the sample data in this process, opens each page in headless
Chromium and saves PNGs. Needs the e2e extra: ``pip install -e ".[e2e]"`` and
``playwright install chromium``.

Usage: ``python tools/screenshots.py [output directory]`` (default ``docs/images``)
"""

from __future__ import annotations

import contextlib
import io
import socket
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import uvicorn
from playwright.sync_api import Browser, sync_playwright

from qualityintel.cli import main as cli_main
from qualityintel.dashboard.app import create_app
from qualityintel.gates.config import load_gate_config
from qualityintel.history.store import HistoryStore
from qualityintel.ingest.batch import import_pipeline
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.models.collection import PipelineCollection
from qualityintel.workspace import Workspace

ROOT = Path(__file__).parents[1]
PIPELINES = ROOT / "samples" / "pipelines" / "cypress-taskboard"
TASKBOARD_JOBS = ("api", "ui-chrome", "ui-firefox", "ui-edge", "component")
TASKBOARD_REPO = "niranjankagri/cypress-typescript-framework"
SHOTS = [
    # (file name, hash route, viewport width, colour scheme, full page)
    ("dashboard-overview.png", "#/", 1280, "light", True),
    ("dashboard-requirements.png", "#/requirements?criticality=critical", 1280, "light", False),
    (
        "dashboard-test-history.png",
        "#/test?key=com.enterprise.automation.tests.ui.CustomerManagementTest%3A%3AadminEditsACustomer",
        1280,
        "light",
        False,
    ),
    ("dashboard-run.png", "#/runs?framework=playwright", 1280, "dark", False),
    ("dashboard-stability.png", "#/stability", 1280, "light", True),
    ("dashboard-executions.png", "#/executions", 1440, "light", True),
    ("dashboard-executions-dark.png", "#/executions", 1440, "dark", True),
    ("dashboard-executions-phone.png", "#/executions", 390, "light", True),
    ("dashboard-trends.png", "#/trends", 1280, "light", False),
    ("dashboard-compare.png", "#/compare?framework=testng&base=f5a40d5&head=1d03232", 1280, "light", False),
    ("dashboard-attention.png", "#/attention", 1280, "light", False),
    ("dashboard-action-center.png", "#/attention", 1280, "light", True),
    ("dashboard-search.png", "#/search?q=checkout", 1280, "light", False),
    ("dashboard-phone.png", "#/", 390, "light", False),
]
# Taken on the two real TaskBoard pipeline executions (samples/pipelines)
PIPELINE_SHOTS = [
    ("dashboard-pipelines.png", f"#/pipelines?jobs={','.join(TASKBOARD_JOBS)}", 1280, "light", True),
    ("dashboard-operations.png", "#/collection", 1280, "light", True),
    ("dashboard-repository-coverage.png", "#/requirements", 1280, "light", True),
]


def main(argv: list[str]) -> int:
    """Serve the samples, capture every entry of ``SHOTS``, stop the server."""
    out = Path(argv[0]) if argv else ROOT / "docs" / "images"
    out.mkdir(parents=True, exist_ok=True)
    # Like real use: the runs and a coverage snapshot come from a history database
    history = Path(tempfile.mkdtemp()) / "quality.db"
    with contextlib.redirect_stdout(io.StringIO()):
        code = cli_main(
            [
                "history",
                "import",
                str(ROOT / "samples" / "results"),
                "--database",
                str(history),
                "--catalog",
                str(ROOT / "samples" / "catalog.toml"),
            ]
        )
    if code != 0:
        print("samples did not import cleanly", file=sys.stderr)
        return 3
    with HistoryStore(history) as store:
        # With the nightly gate, so the overview shows a release decision as a deployment does
        workspace = Workspace(
            load_catalog(ROOT / "samples" / "catalog.toml"),
            store.runs(),
            store.snapshots(),
            gate=load_gate_config(ROOT / "samples" / "gates" / "nightly.toml"),
        )
    pipelines = pipeline_workspace()
    if pipelines is None:
        print("pipeline samples did not import cleanly", file=sys.stderr)
        return 3
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        capture(browser, workspace, SHOTS, out)
        capture(browser, pipelines, PIPELINE_SHOTS, out)
        gate_reports(browser, out)
        browser.close()
    return 0


def pipeline_workspace() -> Workspace | None:
    """Both sample TaskBoard pipelines and their recorded collection outcomes."""
    runs = []
    for folder in sorted(p for p in PIPELINES.iterdir() if p.is_dir()):
        _, commit, run_id = folder.name.split("_")
        batch = import_pipeline(
            {report.stem: [str(report)] for report in sorted(folder.glob("*.json"))},
            run_id,
            commit=commit,
            repository=TASKBOARD_REPO,
        )
        if not batch.complete:
            return None
        runs.extend(batch.runs)
    collected_at = datetime.now(UTC) - timedelta(hours=1)
    collections = [
        PipelineCollection(
            pipeline_id="39238241112",
            attempt=1,
            repository=TASKBOARD_REPO,
            workflow="ci.yml",
            run_number=10,
            branch="main",
            commit="80e331e",
            conclusion="success",
            url="https://github.com/niranjankagri/cypress-typescript-framework/actions/runs/39238241112",
            collected_at=collected_at,
            state="complete",
        ),
        PipelineCollection(
            pipeline_id="38842296207",
            attempt=1,
            repository=TASKBOARD_REPO,
            workflow="ci.yml",
            run_number=6,
            branch="main",
            commit="a15d3c7",
            conclusion="cancelled",
            url="https://github.com/niranjankagri/cypress-typescript-framework/actions/runs/38842296207",
            collected_at=collected_at,
            state="incomplete",
            problems=(
                "job ui-firefox: artifact report-ui-firefox not found "
                "(job not run, cancelled or failed early)",
            ),
        ),
    ]
    return Workspace(load_catalog(PIPELINES / "catalog.toml"), runs, collections=collections)


def capture(
    browser: Browser, workspace: Workspace, shots: list[tuple[str, str, int, str, bool]], out: Path
) -> None:
    """Serve one workspace on a free port and take its screenshots."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = int(probe.getsockname()[1])
    server = uvicorn.Server(
        uvicorn.Config(create_app(workspace), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.05)
    try:
        for name, route, width, scheme, full in shots:
            context = browser.new_context(
                viewport={"width": width, "height": 900 if width > 600 else 844},
                color_scheme=scheme,  # type: ignore[arg-type]
                device_scale_factor=1 if width > 600 else 2,
            )
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{port}/{route}")
            page.locator("#view h1").wait_for()
            page.wait_for_load_state("networkidle")
            page.evaluate(
                """() => {
                  if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
                  document.documentElement.scrollTop = 0;
                  document.body.scrollTop = 0;
                  window.scrollTo(0, 0);
                }"""
            )
            page.screenshot(path=out / name, full_page=full)
            print(f"saved {out / name}")
            context.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def gate_reports(browser: Browser, out: Path) -> None:
    """HTML gate reports produced by the real command: the sample release, the cancelled pipeline."""
    cancelled = PIPELINES / "2026-10-16_a15d3c7_38842296207"
    _, commit, run_id = cancelled.name.split("_")
    gates = {
        "gate-report-release.png": [
            "--catalog",
            str(ROOT / "samples" / "catalog.toml"),
            "--config",
            str(ROOT / "samples" / "gates" / "release.toml"),
            str(ROOT / "samples" / "results"),
        ],
        "gate-report-pipeline.png": [
            "--catalog",
            str(PIPELINES / "catalog.toml"),
            "--config",
            str(PIPELINES / "gate.toml"),
            "--pipeline",
            run_id,
            "--commit",
            commit,
            *[
                arg
                for report in sorted(cancelled.glob("*.json"))
                for arg in ("--job", f"{report.stem}={report}")
            ],
        ],
    }
    for name, args in gates.items():
        with tempfile.TemporaryDirectory() as folder:
            report = Path(folder) / "report.html"
            with contextlib.redirect_stdout(io.StringIO()):
                cli_main(["gate", *args, "--html", str(report)])
            page = browser.new_page(viewport={"width": 1100, "height": 900})
            page.goto(report.as_uri())
            page.screenshot(path=out / name, full_page=True)
            print(f"saved {out / name}")
            page.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
