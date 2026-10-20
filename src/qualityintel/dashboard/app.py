"""FastAPI application: a read-only JSON API over a :class:`Workspace` plus the static front end.

Every route only translates HTTP to a workspace call: query parameters become a
:class:`Scope`, ``KeyError`` becomes 404, a filter value that cannot exist becomes 422.
OpenAPI documentation of the API is served at ``/docs``.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from qualityintel import __version__
from qualityintel.history.analysis import DEFAULTS, HistorySettings
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


def create_app(workspace: Workspace) -> FastAPI:
    """Build the application around one loaded workspace."""
    app = FastAPI(
        title="Quality Intelligence Dashboard",
        version=__version__,
        description="Read-only API over a requirement catalog and imported test results.",
        redoc_url=None,
    )
    app.add_middleware(SecurityHeaders)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """The single-page front end."""
        return FileResponse(STATIC / "index.html")

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, object]:
        """Liveness check with the size of the loaded data."""
        return {
            "status": "ok",
            "version": __version__,
            "requirements": len(workspace.catalog.requirements),
            "runs": len(workspace.runs),
        }

    @app.get("/api/facets", tags=["meta"])
    def facets() -> Facets:
        """Filter values that exist in the data."""
        return workspace.facets()

    @app.get("/api/summary", tags=["coverage"])
    def summary(chosen: FullScope) -> Summary:
        """Coverage metrics, gaps and the execution snapshot."""
        return workspace.summary(chosen)

    @app.get("/api/requirements", tags=["coverage"])
    def requirements(chosen: FullScope, status: str | None = None) -> tuple[RequirementRow, ...]:
        """In-scope requirements; ``status`` drills down to one coverage or execution status."""
        if status is not None:
            _check("status", [status], REQUIREMENT_STATUSES)
        return workspace.requirements(chosen, status=status)

    @app.get("/api/requirements/{requirement_id}", tags=["coverage"])
    def requirement(requirement_id: str, chosen: RunScope) -> RequirementDetail:
        """One requirement with its test cases and their latest executions."""
        try:
            return workspace.requirement(requirement_id, chosen)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown requirement {requirement_id!r}") from None

    @app.get("/api/tests", tags=["executions"])
    def tests(chosen: RunScope, outcome: Outcome | None = None) -> tuple[TestRow, ...]:
        """Every executed test with its counts; ``outcome`` keeps tests whose latest result has it."""
        return workspace.tests(chosen, outcome=outcome)

    @app.get("/api/tests/history", tags=["executions"])
    def test_history(key: Annotated[str, Query(min_length=1)], chosen: RunScope) -> TestHistory:
        """All executions of one test, newest first (the key goes in the query: it contains '/')."""
        try:
            return workspace.test_history(key, chosen)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"no executions of {key!r}") from None

    @app.get("/api/stability", tags=["history"])
    def stability(
        chosen: RunScope,
        window: Annotated[int, Query(ge=1, le=100)] = DEFAULTS.window,
        include_stable: bool = False,
    ) -> StabilityView:
        """Flaky candidates, consistent and new failures, recurring failures, slow-downs, trends."""
        return workspace.stability(chosen, HistorySettings(window=window), include_stable=include_stable)

    @app.get("/api/trends", tags=["history"])
    def trends(chosen: FullScope) -> TrendsView:
        """Daily execution snapshots, per-context run series and recorded coverage snapshots."""
        return workspace.trends(chosen)

    @app.get("/api/runs", tags=["executions"])
    def runs(chosen: RunScope) -> tuple[RunView, ...]:
        """Imported runs, newest first."""
        return workspace.run_list(chosen)

    @app.get("/api/pipelines", tags=["executions"])
    def pipelines(
        chosen: RunScope,
        jobs: Annotated[
            str | None, Query(max_length=2000, description="expected jobs, comma-separated")
        ] = None,
    ) -> PipelinesView:
        """Pipeline executions, newest first; with ``jobs``, the ones missing a job are incomplete."""
        expected = [job.strip() for job in (jobs or "").split(",") if job.strip()]
        return workspace.pipelines(chosen, expected)

    @app.get("/api/runs/{run_id}", tags=["executions"])
    def run(run_id: str) -> RunDetail:
        """One run with all results, failures first."""
        try:
            return workspace.run(run_id)
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
