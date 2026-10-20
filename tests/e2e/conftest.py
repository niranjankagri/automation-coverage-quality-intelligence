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
from qualityintel.workspace import Workspace

SAMPLES = Path(__file__).parents[2] / "samples"


def _free_port() -> int:
    """Ask the OS for a port nobody uses."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    """Start uvicorn in a background thread and wait until it answers."""
    workspace, batch = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    assert batch.complete
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(create_app(workspace), host="127.0.0.1", port=port, log_level="warning")
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
    context = browser.new_context(base_url=base_url, viewport={"width": 1280, "height": 900})
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
