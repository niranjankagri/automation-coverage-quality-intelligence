"""Browser test fixtures: the dashboard on a free port, a Chromium page per test.

Run with ``pytest -m e2e`` after ``playwright install chromium``. The server serves the real
sample data, so the browser sees exactly what a user of the demonstration sees.
"""

import hashlib
import os
import socket
import sys
import threading
import time
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import uvicorn
from playwright.sync_api import Browser, Page, sync_playwright

from qualityintel.dashboard.app import create_app
from qualityintel.history.store import HistoryStore
from qualityintel.ingest.batch import import_pipeline
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.live import LiveData, Sources, load_snapshot
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.results import TestRun
from qualityintel.workspace import Workspace

SAMPLES = Path(__file__).parents[2] / "samples"
PIPELINES = SAMPLES / "pipelines" / "cypress-taskboard"
TASKBOARD_REPO = (
    "niranjankagri/cypress-typescript-framework"  # where these reports come from (samples/README.md)
)
LOGIN = ("qi", "correct horse battery")


def pipeline_runs() -> list[TestRun]:
    """Both sample pipelines, imported as `qi history import --pipeline ... --job ...` would."""
    runs: list[TestRun] = []
    for folder in sorted(p for p in PIPELINES.iterdir() if p.is_dir()):
        _, commit, run_id = folder.name.split("_")
        runs += import_pipeline(
            {r.stem: [str(r)] for r in folder.glob("*.json")},
            run_id,
            commit=commit,
            repository=TASKBOARD_REPO,
        ).runs
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


def taskboard_records() -> list[PipelineCollection]:
    """What collection recorded about the two TaskBoard runs (conclusions as GitHub reports them)."""
    collected_at = datetime.now(UTC) - timedelta(hours=1)
    runs = "https://github.com/niranjankagri/cypress-typescript-framework/actions/runs"
    return [
        PipelineCollection(
            pipeline_id="39238241112",
            attempt=1,
            repository=TASKBOARD_REPO,
            workflow="ci.yml",
            run_number=10,
            branch="main",
            commit="80e331e",
            conclusion="success",
            url=f"{runs}/39238241112",
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
            url=f"{runs}/38842296207",
            collected_at=collected_at,
            state="incomplete",
            problems=(
                "job ui-firefox: artifact report-ui-firefox not found (job not run, cancelled or failed early)",
            ),
        ),
    ]


@pytest.fixture(scope="session")
def collected_url() -> Iterator[str]:
    """The pipeline dashboard with collection records, as a collecting deployment has them."""
    workspace = Workspace(
        load_catalog(PIPELINES / "catalog.toml"), pipeline_runs(), collections=taskboard_records()
    )
    yield from _serve(workspace)


@pytest.fixture
def collected_page(browser: Browser, collected_url: str) -> Iterator[Page]:
    """A page on the dashboard with collection records."""
    yield from _page(browser, collected_url)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """On Windows only: ignore the test servers' unclosed browser sockets reported at garbage collection.

    Warnings are errors (pyproject.toml). On Windows, asyncio's Proactor loop leaves the sockets of
    browser connections that a closed browser context abandoned to the garbage collector, which
    reports them as ``PytestUnraisableExceptionWarning`` in whichever test happens to run, failing
    an unrelated test at random. Only that exact report is ignored, only here; Linux (CI) and every
    other warning are unchanged.
    """
    if sys.platform != "win32":
        return
    marker = pytest.mark.filterwarnings(
        r"ignore:.*(socket\.socket|_ProactorBasePipeTransport\.__del__):pytest.PytestUnraisableExceptionWarning"
    )
    for item in items:
        item.add_marker(marker)


@pytest.fixture(scope="session")
def recurring_url() -> Iterator[str]:
    """Synthetic: one test fails with the same cause in two collected runs of o/r (issue drafts)."""
    runs = []
    for day in (18, 19):
        runs.append(
            TestRun.model_validate(
                {
                    "run_id": f"{day:064d}",
                    "source": f"TEST-checkout-{day}.xml",
                    "started_at": datetime(2026, 10, day, 9, tzinfo=UTC),
                    "pipeline": {"pipeline_id": f"r#{day}", "job": "ui", "repository": "o/r"},
                    "results": [
                        {
                            "classname": "checkout",
                            "name": "pays by card",
                            "outcome": "failed",
                            "failure": {"type": "TimeoutError", "message": "Timeout 30000ms exceeded."},
                        }
                    ],
                }
            )
        )
    record = PipelineCollection(
        pipeline_id="r#19",
        attempt=1,
        repository="o/r",
        workflow="CI",
        conclusion="failure",
        url="https://github.com/o/r/actions/runs/19",
        collected_at=datetime(2026, 10, 19, 12, tzinfo=UTC),
        state="complete",
    )
    yield from _serve(Workspace(load_catalog(SAMPLES / "catalog.toml"), runs, collections=[record]))


@pytest.fixture
def recurring_page(browser: Browser, recurring_url: str) -> Iterator[Page]:
    """A page on the dashboard with one recurring failure."""
    yield from _page(browser, recurring_url)


EDGE_REPO = "e/edge"


def edge_runs() -> list[TestRun]:
    """Synthetic edge cases for the report (docs/report-ui.md), three days of one repository.

    api job: only skipped results (no verdict, so no pass rate). ui-chrome job: ``checkout pays``
    passes, passes, fails (a new failure); ``cart recovers`` fails, passes, passes (recovered);
    ``login works`` passes without a recorded duration. Nothing links to the catalog (not mapped).
    """
    ui = {
        17: [
            ("checkout", "pays", "passed", 2.0),
            ("cart", "recovers", "failed", 1.0),
            ("login", "works", "passed", None),
        ],
        18: [
            ("checkout", "pays", "passed", 2.1),
            ("cart", "recovers", "passed", 1.1),
            ("login", "works", "passed", None),
        ],
        19: [
            ("checkout", "pays", "failed", 2.4),
            ("cart", "recovers", "passed", 1.0),
            ("login", "works", "passed", None),
        ],
    }
    runs = []
    for day, results in ui.items():
        for job, browser, rows in (
            ("ui-chrome", "chrome", results),
            ("api", None, [("health", "answers", "skipped", None), ("orders", "list", "skipped", 0.2)]),
        ):
            runs.append(
                TestRun.model_validate(
                    {
                        "run_id": hashlib.sha256(f"{job}-{day}".encode()).hexdigest(),
                        "source": f"{job}-{day}.xml",
                        "started_at": datetime(2026, 10, day, 9, tzinfo=UTC),
                        "context": {"framework": "playwright", "browser": browser, "environment": "ci"},
                        "pipeline": {
                            "pipeline_id": f"e#{day}",
                            "job": job,
                            "repository": EDGE_REPO,
                            "commit": f"c0ffee{day}",
                            "branch": "main",
                        },
                        "results": [
                            {
                                "classname": cls,
                                "name": name,
                                "outcome": outcome,
                                "duration_seconds": seconds,
                                **(
                                    {
                                        "failure": {
                                            "type": "AssertionError",
                                            "message": "expected 3 items, got 2",
                                        }
                                    }
                                    if outcome == "failed"
                                    else {}
                                ),
                            }
                            for cls, name, outcome, seconds in rows
                        ],
                    }
                )
            )
    return runs


@pytest.fixture(scope="session")
def edge_url() -> Iterator[str]:
    """The edge cases, with a stale (3 days old) and an incomplete collection record."""
    old = datetime.now(UTC) - timedelta(days=3)
    records = [
        PipelineCollection(
            pipeline_id=f"e#{day}",
            attempt=1,
            repository=EDGE_REPO,
            workflow="CI",
            conclusion="failure" if day == 19 else "success",
            url=f"https://github.com/{EDGE_REPO}/actions/runs/{day}",
            collected_at=old - timedelta(days=19 - day),
            state="incomplete" if day == 18 else "complete",
            problems=("job ui-firefox: artifact report-ui-firefox not found",) if day == 18 else (),
        )
        for day in (17, 18, 19)
    ]
    yield from _serve(Workspace(load_catalog(SAMPLES / "catalog.toml"), edge_runs(), collections=records))


@pytest.fixture
def edge_page(browser: Browser, edge_url: str) -> Iterator[Page]:
    """A page on the report's edge cases."""
    yield from _page(browser, edge_url)


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


# The engine is chosen with QI_E2E_BROWSER (chromium, firefox, webkit); CI runs all three
ENGINE = os.environ.get("QI_E2E_BROWSER", "chromium")


@pytest.fixture(scope="session")
def browser() -> Iterator[Browser]:
    """One headless browser of the chosen engine for the whole session."""
    with sync_playwright() as playwright:
        launched = getattr(playwright, ENGINE).launch()
        yield launched
        launched.close()


@pytest.fixture
def chromium_only() -> None:
    """Skip tests that use Chromium-only features (clipboard permissions) in other engines."""
    if ENGINE != "chromium":
        pytest.skip(f"clipboard permissions are a Chromium feature; engine is {ENGINE}")


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
    if ENGINE == "webkit":
        # WebKit logs a request to this page's own API that a reload cancelled as failing "due to
        # access control checks"; there is no access control on a same-origin request
        own_api = f"{url.split('//', 1)[-1]}/api/"  # host:port/api/ (WebKit shortens the URL)
        allowed += [e for e in errors if "access control checks" in e and own_api in e]
    assert [e for e in errors if e not in allowed] == []


@pytest.fixture(scope="session", autouse=True)
def _record_browser(record_testsuite_property: Callable[[str, object], None]) -> None:
    """Write browser=chromium into the JUnit file.

    The self-gate then sees these results as their own run context instead of mixing them with
    the unit-test run (docs/quality-gates.md).
    """
    record_testsuite_property("browser", "chromium")
