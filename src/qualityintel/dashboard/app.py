"""FastAPI application: a read-only JSON API over a :class:`Workspace` plus the static front end.

Every route only translates HTTP to a workspace call: query parameters become a
:class:`Scope`, ``KeyError`` becomes 404, a filter value that cannot exist becomes 422.
OpenAPI documentation of the API is served at ``/docs``.
"""

from __future__ import annotations

import base64
import binascii
import contextlib
import hmac
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from qualityintel import __version__
from qualityintel.history.analysis import DEFAULTS, HistorySettings
from qualityintel.live import LiveData
from qualityintel.models.enums import Criticality, Outcome, TestType
from qualityintel.traceability.coverage import UNSPECIFIED, Filters
from qualityintel.traceability.report import RunFilters
from qualityintel.workspace import (
    Facets,
    PipelinesView,
    RequirementDetail,
    RequirementRow,
    RunDetail,
    RunView,
    Scope,
    StabilityView,
    Summary,
    TestHistory,
    TestRow,
    TrendsView,
    View,
    Workspace,
)

STATIC = Path(__file__).parent / "static"
REQUIREMENT_STATUSES = frozenset(
    {"no tests", "not automated", "automated", "passing", "failing", "skipped", "not run"}
)
# The front end loads nothing from other origins and runs no inline script
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
)

ListQuery = Annotated[list[str] | None, Query()]


def run_scope(
    framework: ListQuery = None,
    environment: ListQuery = None,
    browser: ListQuery = None,
    build: ListQuery = None,
    since: date | None = None,
    until: date | None = None,
) -> Scope:
    """Run filters from query parameters (``?browser=firefox&browser=chrome&since=2026-10-13``)."""
    if since is not None and until is not None and since > until:
        raise HTTPException(status_code=422, detail=f"since ({since}) is after until ({until})")
    return Scope(
        run_filters=RunFilters(
            frameworks=frozenset(framework or ()),
            environments=frozenset(environment or ()),
            browsers=frozenset(browser or ()),
            builds=frozenset(build or ()),
            since=since,
            until=until,
        )
    )


def full_scope(
    feature: ListQuery = None,
    criticality: ListQuery = None,
    platform: ListQuery = None,
    test_type: ListQuery = None,
    framework: ListQuery = None,
    environment: ListQuery = None,
    browser: ListQuery = None,
    build: ListQuery = None,
    since: date | None = None,
    until: date | None = None,
) -> Scope:
    """Catalog and run filters; values that can never match an enum are a client error."""
    _check("criticality", criticality or [], {c.value for c in Criticality})
    _check("test_type", test_type or [], {t.value for t in TestType})
    runs = run_scope(framework, environment, browser, build, since, until).run_filters
    return Scope(
        filters=Filters(
            features=frozenset(feature or ()),
            criticalities=frozenset(criticality or ()),
            platforms=frozenset(platform or ()),
            test_types=frozenset(test_type or ()),
            frameworks=runs.frameworks,
        ),
        run_filters=runs,
    )


FullScope = Annotated[Scope, Depends(full_scope)]
RunScope = Annotated[Scope, Depends(run_scope)]


class SecurityHeaders(BaseHTTPMiddleware):
    """Strict headers for the dashboard pages; /docs keeps FastAPI's defaults (it loads a CDN)."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add the headers after the route has answered."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        if not request.url.path.startswith(("/docs", "/openapi.json")):
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        return response


class BasicAuth(BaseHTTPMiddleware):
    """HTTP basic authentication for every path, when a password is configured (docs/security.md).

    The browser asks once and then sends the credentials with every request, including the
    front end's own API calls. Both parts are compared in constant time.
    """

    def __init__(self, app: object, user: str, password: str) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.expected = (user.encode(), password.encode())

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Answer 401 unless the request carries the right user and password."""
        scheme, _, token = request.headers.get("authorization", "").partition(" ")
        user = password = b""
        if scheme.lower() == "basic":
            try:
                user, _, password = base64.b64decode(token, validate=True).partition(b":")
            except (binascii.Error, ValueError):
                user = password = b""
        # Both comparisons always run, so the timing does not tell which part was wrong
        user_ok = hmac.compare_digest(user, self.expected[0])
        password_ok = hmac.compare_digest(password, self.expected[1])
        if user_ok and password_ok:
            return await call_next(request)
        return Response(
            "authentication required\n",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="qi dashboard", charset="UTF-8"'},
            media_type="text/plain",
        )


class DataStatus(View):
    """Freshness of the data the dashboard shows (``/api/status``)."""

    version: str
    loaded_at: datetime
    sources_modified_at: datetime | None
    latest_run_started_at: datetime | None
    refresh_seconds: float
    last_check: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    stale: bool
    collections: int
    latest_collection_at: datetime | None
    incomplete_collections_7d: int
    collection_problems: tuple[str, ...]


def create_app(data: Workspace | LiveData, credentials: tuple[str, str] | None = None) -> FastAPI:
    """Build the application around the dashboard data.

    Args:
        data: The data to serve: a fixed workspace, or :class:`LiveData` that reloads when its
            sources change (each request answers from one complete snapshot).
        credentials: ``(user, password)`` to require on every request; ``None`` for none
            (the command line only allows that on this machine's loopback address).
    """
    live = data if isinstance(data, LiveData) else LiveData.fixed(data)

    def current() -> Workspace:
        """The workspace of the snapshot that is current now."""
        return live.current().workspace

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        """Background refresh while the server runs."""
        live.start()
        try:
            yield
        finally:
            live.stop()

    app = FastAPI(
        lifespan=lifespan,
        title="Quality Intelligence Dashboard",
        version=__version__,
        description="Read-only API over a requirement catalog and imported test results.",
        redoc_url=None,
    )
    app.add_middleware(SecurityHeaders)
    if credentials is not None:
        # Added last, so it runs first: nothing is answered before the check
        app.add_middleware(BasicAuth, user=credentials[0], password=credentials[1])
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """The single-page front end."""
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, object]:
        """Liveness check with the size of the loaded data."""
        workspace = current()
        return {
            "status": "ok",
            "version": __version__,
            "requirements": len(workspace.catalog.requirements),
            "runs": len(workspace.runs),
        }

    @app.get("/api/status", tags=["meta"])
    def status(check: bool = False) -> DataStatus:
        """When the data was loaded, how fresh it is, and the last refresh error.

        ``check=true`` looks for new data now (at most once every few seconds); the answer
        describes the data current after that check.
        """
        if check:
            live.check(force=True)
        state = live.status()
        snapshot = live.current()
        starts = [run.started_at for run in snapshot.workspace.runs if run.started_at is not None]
        week_ago = datetime.now(UTC) - timedelta(days=7)
        recent = [c for c in snapshot.collections if c.collected_at >= week_ago]
        incomplete = [c for c in recent if c.state == "incomplete"]
        return DataStatus(
            version=state.version,
            loaded_at=state.loaded_at,
            sources_modified_at=state.sources_modified_at,
            latest_run_started_at=max(starts, default=None),
            refresh_seconds=state.interval_seconds,
            last_check=state.last_check,
            last_error=state.last_error,
            last_error_at=state.last_error_at,
            stale=state.stale,
            collections=len(snapshot.collections),
            latest_collection_at=max((c.collected_at for c in snapshot.collections), default=None),
            incomplete_collections_7d=len(incomplete),
            collection_problems=tuple(f"{c.pipeline_id}: {p}" for c in incomplete for p in c.problems)[:20],
        )

    @app.get("/api/facets", tags=["meta"])
    def facets() -> Facets:
        """Filter values that exist in the data."""
        return current().facets()

    @app.get("/api/summary", tags=["coverage"])
    def summary(chosen: FullScope) -> Summary:
        """Coverage metrics, gaps and the execution snapshot."""
        return current().summary(chosen)

    @app.get("/api/requirements", tags=["coverage"])
    def requirements(chosen: FullScope, status: str | None = None) -> tuple[RequirementRow, ...]:
        """In-scope requirements; ``status`` drills down to one coverage or execution status."""
        if status is not None:
            _check("status", [status], REQUIREMENT_STATUSES)
        return current().requirements(chosen, status=status)

    @app.get("/api/requirements/{requirement_id}", tags=["coverage"])
    def requirement(requirement_id: str, chosen: RunScope) -> RequirementDetail:
        """One requirement with its test cases and their latest executions."""
        try:
            return current().requirement(requirement_id, chosen)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown requirement {requirement_id!r}") from None

    @app.get("/api/tests", tags=["executions"])
    def tests(chosen: RunScope, outcome: Outcome | None = None) -> tuple[TestRow, ...]:
        """Every executed test with its counts; ``outcome`` keeps tests whose latest result has it."""
        return current().tests(chosen, outcome=outcome)

    @app.get("/api/tests/history", tags=["executions"])
    def test_history(key: Annotated[str, Query(min_length=1)], chosen: RunScope) -> TestHistory:
        """All executions of one test, newest first (the key goes in the query: it contains '/')."""
        try:
            return current().test_history(key, chosen)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no executions of {key!r}") from None

    @app.get("/api/stability", tags=["history"])
    def stability(
        chosen: RunScope,
        window: Annotated[int, Query(ge=1, le=100)] = DEFAULTS.window,
        include_stable: bool = False,
    ) -> StabilityView:
        """Flaky candidates, consistent and new failures, recurring failures, slow-downs, trends."""
        return current().stability(chosen, HistorySettings(window=window), include_stable=include_stable)

    @app.get("/api/trends", tags=["history"])
    def trends(chosen: FullScope) -> TrendsView:
        """Daily execution snapshots, per-context run series and recorded coverage snapshots."""
        return current().trends(chosen)

    @app.get("/api/runs", tags=["executions"])
    def runs(chosen: RunScope) -> tuple[RunView, ...]:
        """Imported runs, newest first."""
        return current().run_list(chosen)

    @app.get("/api/pipelines", tags=["executions"])
    def pipelines(
        chosen: RunScope,
        jobs: Annotated[
            str | None, Query(max_length=2000, description="expected jobs, comma-separated")
        ] = None,
    ) -> PipelinesView:
        """Pipeline executions, newest first; with ``jobs``, the ones missing a job are incomplete."""
        expected = [job.strip() for job in (jobs or "").split(",") if job.strip()]
        return current().pipelines(chosen, expected)

    @app.get("/api/runs/{run_id}", tags=["executions"])
    def run(run_id: str) -> RunDetail:
        """One run with all results, failures first."""
        try:
            return current().run(run_id)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown run {run_id!r}") from None

    return app


def _check(name: str, values: list[str], allowed: set[str] | frozenset[str]) -> None:
    """Reject values that can never match (``unspecified`` is always allowed for enums)."""
    wrong = [v for v in values if v not in allowed and v != UNSPECIFIED]
    if wrong:
        raise HTTPException(
            status_code=422,
            detail=f"{name}: unknown value(s) {', '.join(map(repr, wrong))}; "
            f"allowed: {', '.join(sorted(allowed))}",
        )
