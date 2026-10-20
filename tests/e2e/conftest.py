"""Browser test fixtures: the dashboard on a free port, a Chromium page per test.

Run with ``pytest -m e2e`` after ``playwright install chromium``. The server serves the real
sample data, so the browser sees exactly what a user of the demonstration sees.
"""

import socket
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, sync_playwright

from qualityintel.dashboard.app import create_app
from qualityintel.history.store import HistoryStore
from qualityintel.ingest.batch import import_pipeline
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.live import LiveData, Sources, load_snapshot
from qualityintel.models.results import TestRun
from qualityintel.workspace import Workspace

SAMPLES = Path(__file__).parents[2] / "samples"
PIPELINES = SAMPLES / "pipelines" / "cypress-taskboard"
LOGIN = ("qi", "correct horse battery")


def pipeline_runs() -> list[TestRun]:
    """Both sample pipelines, imported as `qi history import --pipeline ... --job ...` would."""
    runs: list[TestRun] = []
    for folder in sorted(p for p in PIPELINES.iterdir() if p.is_dir()):
        _, commit, run_id = folder.name.split("_")
        runs += import_pipeline({r.stem: [str(r)] for r in folder.glob("*.json")}, run_id, commit=commit).runs
    return runs


def _free_port() -> int:
    """Ask the OS for a port nobody uses."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    """The dashboard on the sample JUnit results (what the demonstration shows)."""
    workspace, batch = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    assert batch.complete
    yield from _serve(workspace)


@pytest.fixture(scope="session")
def pipelines_url() -> Iterator[str]:
    """The dashboard on the two real TaskBoard pipeline executions (samples/pipelines)."""
    yield from _serve(Workspace(load_catalog(PIPELINES / "catalog.toml"), pipeline_runs()))


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[tuple[str, Sources]]:
    """A dashboard on a history database the test can change (refresh every second)."""
    database = tmp_path / "quality.db"
    with HistoryStore(database) as store:
        store.add_all(
            import_pipeline({"api": [str(SAMPLES / "results" / "pytest-notes-api")]}, "p#1").runs[:3]
        )
    sources = Sources(SAMPLES / "catalog.toml", database)
    live = LiveData(load_snapshot(sources), sources, interval_seconds=1)
    for url in _serve(live):
        yield url, sources


@pytest.fixture
def live_page(browser: Browser, live_server: tuple[str, Sources]) -> Iterator[Page]:
    """A page on the live-data dashboard."""
    yield from _page(browser, live_server[0])


@pytest.fixture(scope="session")
def secured_url() -> Iterator[str]:
    """The sample dashboard with a login (QI_DASHBOARD_PASSWORD set)."""
    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    yield from _serve(workspace, LOGIN)


def _serve(workspace: Workspace | LiveData, credentials: tuple[str, str] | None = None) -> Iterator[str]:
    """Start uvicorn in a background thread, wait until it answers, stop it afterwards."""
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(workspace, credentials), host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("dashboard server did not start within 15 s")
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """One headless Chromium for the whole session."""
    with sync_playwright() as playwright:
        chromium = playwright.chromium.launch()
        yield chromium
        chromium.close()


@pytest.fixture
def page(browser: Browser, base_url: str) -> Iterator[Page]:
    """A fresh page; console errors fail the test (they mean broken front-end code)."""
    yield from _page(browser, base_url)


@pytest.fixture
def pipelines_page(browser: Browser, pipelines_url: str) -> Iterator[Page]:
    """A fresh page on the pipeline dashboard, with the same console-error check."""
    yield from _page(browser, pipelines_url)


def _page(browser: Browser, url: str) -> Iterator[Page]:
    """New context and page; fails on console errors after the test."""
    context = browser.new_context(base_url=url, viewport={"width": 1280, "height": 900})
    new_page = context.new_page()
    errors: list[str] = []
    new_page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    new_page.on("pageerror", lambda error: errors.append(str(error)))
    yield new_page
    context.close()
    allowed = [e for e in errors if "Failed to load resource" in e]  # deliberate 404/500 in some tests
    assert [e for e in errors if e not in allowed] == []


@pytest.fixture(scope="session", autouse=True)
def _record_browser(record_testsuite_property: Callable[[str, object], None]) -> None:
    """Write browser=chromium into the JUnit file.

    The self-gate then sees these results as their own run context instead of mixing them with
    the unit-test run (docs/quality-gates.md).
    """
    record_testsuite_property("browser", "chromium")
