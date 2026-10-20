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
from pathlib import Path

import uvicorn
from playwright.sync_api import sync_playwright

from qualityintel.cli import main as cli_main
from qualityintel.dashboard.app import create_app
from qualityintel.history.store import HistoryStore
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.workspace import Workspace

ROOT = Path(__file__).parents[1]
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
    ("dashboard-trends.png", "#/trends", 1280, "light", False),
    ("dashboard-phone.png", "#/", 390, "light", False),
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
        workspace = Workspace(
            load_catalog(ROOT / "samples" / "catalog.toml"), store.runs(), store.snapshots()
        )
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
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for name, route, width, scheme, full in SHOTS:
                context = browser.new_context(
                    viewport={"width": width, "height": 900 if width > 600 else 844},
                    color_scheme=scheme,  # type: ignore[arg-type]
                    device_scale_factor=1 if width > 600 else 2,
                )
                page = context.new_page()
                page.goto(f"http://127.0.0.1:{port}/{route}")
                page.locator("#view h1").wait_for()
                page.wait_for_load_state("networkidle")
                page.screenshot(path=out / name, full_page=full)
                print(f"saved {out / name}")
                context.close()
            # The release gate's HTML report, produced by the real command
            with tempfile.TemporaryDirectory() as folder:
                report = Path(folder) / "release.html"
                gate = [
                    "gate",
                    "--catalog",
                    str(ROOT / "samples" / "catalog.toml"),
                    "--config",
                    str(ROOT / "samples" / "gates" / "release.toml"),
                    str(ROOT / "samples" / "results"),
                    "--html",
                    str(report),
                ]
                with contextlib.redirect_stdout(io.StringIO()):
                    cli_main(gate)
                page = browser.new_page(viewport={"width": 1100, "height": 900})
                page.goto(report.as_uri())
                page.screenshot(path=out / "gate-report-release.png", full_page=True)
                print(f"saved {out / 'gate-report-release.png'}")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
