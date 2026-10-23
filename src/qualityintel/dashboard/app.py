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
import json
import math
import os
import re
import time
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from qualityintel import __version__
from qualityintel.history.analysis import DEFAULTS, HistorySettings
from qualityintel.links import dashboard_path
from qualityintel.live import LiveData
from qualityintel.models.enums import Criticality, Outcome, TestType
from qualityintel.reporting.digest import render_digest
from qualityintel.reporting.investigation import summarise_comparison, summarise_test
from qualityintel.search import MAX_QUERY, QueryError
from qualityintel.traceability.coverage import UNSPECIFIED, Filters
from qualityintel.traceability.report import RunFilters
from qualityintel.workspace import (
    AttentionView,
    BuildComparisonView,
    CollectionHealthView,
    DigestView,
    ExecutionDashboard,
    ExecutionOption,
    Facets,
    GapsView,
    GateHistoryView,
    IssueSuggestionsView,
    PipelinesView,
    ReadinessView,
    RegressionsView,
    ReportOverview,
    RepositoryTrendsView,
    RequirementDetail,
    RequirementMatrix,
    RequirementRow,
    RunDetail,
    RunView,
    Scope,
    SearchView,
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
COVERAGE_STATUSES = frozenset({"no tests", "not automated", "automated"})
EXECUTION_STATUSES = frozenset({"not automated", "not run", "skipped", "passing", "failing"})
ATTENTION_KINDS = frozenset(
    {
        "newly failing",
        "incomplete pipeline",
        "critical gap",
        "recurring failure",
        "duration regression",
        "flaky candidate",
        "overdue collection",
    }
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
    repository: ListQuery = None,
    job: ListQuery = None,
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
            repositories=frozenset(repository or ()),
            jobs=frozenset(job or ()),
            since=since,
            until=until,
        )
    )


def full_scope(
    feature: ListQuery = None,
    owner: ListQuery = None,
    criticality: ListQuery = None,
    platform: ListQuery = None,
    test_type: ListQuery = None,
    framework: ListQuery = None,
    environment: ListQuery = None,
    browser: ListQuery = None,
    build: ListQuery = None,
    since: date | None = None,
    until: date | None = None,
    repository: ListQuery = None,
    job: ListQuery = None,
) -> Scope:
    """Catalog and run filters; values that can never match an enum are a client error."""
    _check("criticality", criticality or [], {c.value for c in Criticality})
    _check("test_type", test_type or [], {t.value for t in TestType})
    runs = run_scope(framework, environment, browser, build, since, until, repository, job).run_filters
    return Scope(
        filters=Filters(
            features=frozenset(feature or ()),
            owners=frozenset(owner or ()),
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
    """Strict headers for the dashboard pages; /docs keeps FastAPI's defaults (it loads a CDN).

    Over https (directly, or behind a trusted proxy that says so) browsers are told to use
    https only (HSTS). API answers are never stored by shared caches when a login protects
    them, and always revalidated otherwise, so nobody sees an older snapshot.
    """

    def __init__(self, app: object, private: bool) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.private = private

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Add the headers after the route has answered."""
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=(), payment=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        if request.url.path in ("/", "/next/") or request.url.path.startswith(("/api/", "/static/")):
            response.headers["Cache-Control"] = "private, no-store" if self.private else "no-cache"
        if not request.url.path.startswith(("/docs", "/openapi.json")):
            response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        return response


class AccessLog(BaseHTTPMiddleware):
    """One JSON line per request on standard output, for a hosting platform's log search.

    Only method, path, status and duration: no query string (it can name tests), no client
    address, no headers (they can carry the login).
    """

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Time the request and log it after the answer."""
        started = time.perf_counter()
        response = await call_next(request)
        entry = {
            "time": datetime.now(UTC).isoformat(timespec="seconds"),
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "ms": round((time.perf_counter() - started) * 1000, 1),
        }
        print(json.dumps(entry), flush=True)
        return response


class LoginThrottle:
    """Failed logins per client address in a sliding window; too many lock that address out.

    Kept in memory (one process); bounded, so a flood of addresses cannot exhaust memory: the
    oldest entries are dropped first. A correct login does not clear the count, so guessing
    between correct logins of someone else from the same address gains nothing.
    """

    def __init__(self, limit: int = 10, window_seconds: float = 300.0, max_clients: int = 10_000) -> None:
        self.limit = limit
        self.window = window_seconds
        self.max_clients = max_clients
        self._failures: dict[str, list[float]] = {}

    def retry_after(self, client: str, now: float) -> int:
        """Seconds until ``client`` may try again; 0 when it may try now."""
        recent = [t for t in self._failures.get(client, ()) if now - t < self.window]
        if recent:
            self._failures[client] = recent
        else:
            self._failures.pop(client, None)
        if len(recent) < self.limit:
            return 0
        # Allowed again once enough failures have left the window to bring the count below the limit
        return max(1, math.ceil(recent[len(recent) - self.limit] + self.window - now))

    def failed(self, client: str, now: float) -> None:
        """Record a failed login of ``client``."""
        if client not in self._failures and len(self._failures) >= self.max_clients:
            del self._failures[next(iter(self._failures))]
        self._failures.setdefault(client, []).append(now)


class BasicAuth(BaseHTTPMiddleware):
    """HTTP basic authentication for every path, when a password is configured (docs/security.md).

    The browser asks once and then sends the credentials with every request, including the
    front end's own API calls. Both parts are compared in constant time.
    """

    def __init__(self, app: object, user: str, password: str, throttle: LoginThrottle | None = None) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self.expected = (user.encode(), password.encode())
        self.throttle = throttle or LoginThrottle()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Answer 401 unless the user and password are right; 429 after too many wrong ones.

        The lock-out is checked first, so a guess from a locked-out address is not even tried.
        """
        client = request.client.host if request.client else "unknown"
        now = time.monotonic()
        wait = self.throttle.retry_after(client, now)
        if wait:
            return Response(
                "too many failed logins; try again later\n",
                status_code=429,
                headers={"Retry-After": str(wait)},
                media_type="text/plain",
            )
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
        if token:  # the browser's first request carries no credentials: not a failed login
            self.throttle.failed(client, now)
        return Response(
            "authentication required\n",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="qi dashboard", charset="UTF-8"'},
            media_type="text/plain",
        )


def deployed_commit() -> str | None:
    """The source commit of this deployment (docs/deployment.md), ``None`` when not known.

    ``QI_BUILD_COMMIT`` wins; Render sets ``RENDER_GIT_COMMIT`` for every deploy. Only a hex
    commit id is reported, so a misconfigured value never reaches the page.
    """
    for name in ("QI_BUILD_COMMIT", "RENDER_GIT_COMMIT"):
        value = os.environ.get(name, "").strip().lower()
        if re.fullmatch(r"[0-9a-f]{7,40}", value):
            return value
    return None


class InvestigationSummary(View):
    """A copyable summary (docs/dashboard.md, Summaries)."""

    text: str
    markdown: str


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


def create_app(
    data: Workspace | LiveData,
    credentials: tuple[str, str] | None = None,
    collection_hours: float = 26.0,
    collection_url: str | None = None,
    access_log: bool = False,
) -> FastAPI:
    """Build the application around the dashboard data.

    Args:
        data: The data to serve: a fixed workspace, or :class:`LiveData` that reloads when its
            sources change (each request answers from one complete snapshot).
        credentials: ``(user, password)`` to require on every request; ``None`` for none
            (the command line only allows that on this machine's loopback address).
        collection_hours: Hours after which a repository's last collection counts as overdue.
        collection_url: Link to the collection workflow, shown on the Collection page.
        access_log: Log every request as a JSON line (``QI_ACCESS_LOG=json``).
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
    app.add_middleware(SecurityHeaders, private=credentials is not None)
    if credentials is not None:
        # Added last, so it runs first: nothing is answered before the check
        app.add_middleware(BasicAuth, user=credentials[0], password=credentials[1])
    if access_log:
        # Added last, so it runs first: refused requests (401, 429) are logged too
        app.add_middleware(AccessLog)
    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        """The single-page front end."""
        return FileResponse(STATIC / "index.html")

    @app.get("/next/", include_in_schema=False)
    def next_report() -> FileResponse:
        """The new report-style front end (docs/report-ui.md), served beside the current one."""
        return FileResponse(STATIC / "next" / "index.html")

    @app.get("/next", include_in_schema=False)
    def next_report_slash() -> RedirectResponse:
        """``/next`` without the slash: the page's relative asset links need it."""
        return RedirectResponse("/next/", status_code=308)

    @app.get("/api/report/overview", tags=["report"])
    def report_overview(chosen: RunScope) -> ReportOverview:
        """The latest snapshot as the report overview: totals, suites, failure causes, trend."""
        return current().report_overview(chosen)

    @app.get("/api/health", tags=["meta"])
    def health() -> dict[str, object]:
        """Liveness check with the size of the loaded data, the deployed commit and the catalog notice."""
        workspace = current()
        return {
            "status": "ok",
            "version": __version__,
            "commit": deployed_commit(),
            "requirements": len(workspace.catalog.requirements),
            "runs": len(workspace.runs),
            "catalog_notice": workspace.catalog.notice,
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

    @app.get("/api/gaps", tags=["coverage"])
    def gaps(chosen: FullScope) -> GapsView:
        """Requirements without automated coverage in priority order, grouped by owner."""
        return current().gaps(chosen)

    @app.get("/api/readiness", tags=["coverage"])
    def readiness(chosen: FullScope) -> ReadinessView:
        """Release status of the scope (ready / at risk / blocked / unknown) by the documented policy."""
        return current().readiness(chosen, stale=live.status().stale)

    @app.get("/api/requirements", tags=["coverage"])
    def requirements(
        chosen: FullScope,
        status: str | None = None,
        observed: bool | None = None,
        stale: bool | None = None,
        coverage_status: str | None = None,
        execution_status: str | None = None,
    ) -> tuple[RequirementRow, ...]:
        """In-scope requirements, optionally filtered by status, linked result evidence, or staleness."""
        if status is not None:
            _check("status", [status], REQUIREMENT_STATUSES)
        if coverage_status is not None:
            _check("coverage_status", [coverage_status], COVERAGE_STATUSES)
        if execution_status is not None:
            _check("execution_status", [execution_status], EXECUTION_STATUSES)
        return current().requirements(
            chosen,
            status=status,
            observed=observed,
            stale=stale,
            coverage_status=coverage_status,
            execution_status=execution_status,
        )

    @app.get("/api/search", tags=["investigation"])
    def search(
        chosen: RunScope,
        q: Annotated[str, Query(max_length=MAX_QUERY * 2)],
        limit: Annotated[int, Query(ge=1, le=50)] = 20,
    ) -> SearchView:
        """Everything whose text contains every word of ``q`` (2-100 characters), grouped by kind.

        Searched: repositories, workflows, pipelines, tests, requirements and failure messages. Each
        group shows at most ``limit`` results and its full count; repository and date filters apply.
        """
        try:
            return current().search(q, chosen, limit)
        except QueryError as error:
            raise HTTPException(status_code=422, detail=str(error)) from None

    def page_link(link: str | None) -> str | None:
        """A same-site path for a copied summary; external or malformed destinations are omitted."""
        return dashboard_path(link)

    @app.get("/api/tests/summary", tags=["investigation"])
    def summary_of_test(
        key: Annotated[str, Query(min_length=1, max_length=2000)],
        chosen: RunScope,
        link: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> InvestigationSummary:
        """A copyable summary of one test's investigation, as text and Markdown."""
        try:
            history = current().test_history(key, chosen)
        except KeyError:
            raise HTTPException(
                status_code=404, detail=f"no results for test {key!r} in this scope"
            ) from None
        made = summarise_test(history, live.current().loaded_at, page_link(link), current().catalog.notice)
        return InvestigationSummary(text=made.text, markdown=made.markdown)

    @app.get("/api/compare/summary", tags=["investigation"])
    def summary_of_comparison(
        base: Annotated[str, Query(min_length=1, max_length=200)],
        head: Annotated[str, Query(min_length=1, max_length=200)],
        chosen: RunScope,
        link: Annotated[str | None, Query(max_length=2000)] = None,
    ) -> InvestigationSummary:
        """A copyable summary of a build comparison, as text and Markdown (same rules as /api/compare)."""
        if base == head:
            raise HTTPException(status_code=422, detail="choose two different builds")
        try:
            comparison = current().compare_builds(base, head, chosen)
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail=f"no runs of build {error.args[0]!r} in this scope"
            ) from None
        made = summarise_comparison(
            comparison, live.current().loaded_at, page_link(link), current().catalog.notice
        )
        return InvestigationSummary(text=made.text, markdown=made.markdown)

    @app.get("/api/attention", tags=["investigation"])
    def attention(chosen: FullScope, kind: str | None = None) -> AttentionView:
        """Findings that need attention, each with its evidence, state and links (docs/attention.md)."""
        if kind is not None:
            _check("kind", [kind], ATTENTION_KINDS)
        return current().attention(chosen, kind=kind)

    @app.get("/api/requirements/matrix", tags=["coverage"])
    def requirement_matrix(chosen: FullScope) -> RequirementMatrix:
        """Requirements in scope by criticality and by feature, with coverage, execution and stale counts."""
        return current().requirement_matrix(chosen)

    @app.get("/api/requirements/{requirement_id}", tags=["coverage"])
    def requirement(requirement_id: str, chosen: RunScope) -> RequirementDetail:
        """One requirement with its test cases and their latest executions."""
        try:
            return current().requirement(requirement_id, chosen)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown requirement {requirement_id!r}") from None

    @app.get("/api/execution-options", tags=["executions"])
    def execution_options() -> tuple[ExecutionOption, ...]:
        """Recorded repository/type/browser combinations for progressive navigation."""
        return current().execution_options()

    @app.get("/api/executions", tags=["executions"])
    def execution_dashboard(
        chosen: RunScope,
        limit: Annotated[int, Query(ge=1, le=100)] = 10,
        suite: Annotated[str | None, Query(max_length=500)] = None,
        kind: Annotated[str | None, Query(max_length=50)] = None,
    ) -> ExecutionDashboard:
        """Historical test-execution dashboard; counts all reports in scope, not the latest snapshot."""
        return current().execution_dashboard(chosen, limit, suite, kind)

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

    @app.get("/api/builds", tags=["history"])
    def builds(chosen: RunScope) -> tuple[str, ...]:
        """Builds in scope in the order they first ran (the build filter itself is ignored)."""
        return current().builds(chosen)

    @app.get("/api/compare", tags=["history"])
    def compare(
        base: Annotated[str, Query(min_length=1, max_length=200)],
        head: Annotated[str, Query(min_length=1, max_length=200)],
        chosen: RunScope,
    ) -> BuildComparisonView:
        """Changes from build ``base`` to build ``head`` where both ran the same suite."""
        if base == head:
            raise HTTPException(status_code=422, detail="choose two different builds")
        try:
            return current().compare_builds(base, head, chosen)
        except KeyError as error:
            raise HTTPException(
                status_code=404, detail=f"no runs of build {error.args[0]!r} in this scope"
            ) from None

    @app.get("/api/regressions", tags=["history"])
    def regressions(chosen: RunScope) -> RegressionsView:
        """Each suite's newest build against its previous build on the same branch (build filter ignored)."""
        return current().regressions(chosen)

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

    @app.get("/api/gate-history", tags=["history"])
    def gate_history(chosen: FullScope) -> GateHistoryView:
        """The release gate on each day's snapshot (last 30 days with runs) and the days it changed."""
        return current().gate_history(chosen)

    @app.get("/api/digest", tags=["history"])
    def digest(chosen: FullScope, day: date | None = None) -> DigestView:
        """What one day (default: the newest day with runs) added to the history (docs/digest.md)."""
        return current().digest(chosen, day)

    @app.get("/api/digest/summary", tags=["history"])
    def digest_summary(chosen: FullScope, day: date | None = None) -> InvestigationSummary:
        """The digest as copyable text and Markdown, with dashboard links relative to this site."""
        made = render_digest(current().digest(chosen, day))
        return InvestigationSummary(text=made.text, markdown=made.markdown)

    @app.get("/api/issue-suggestions", tags=["investigation"])
    def issue_suggestions(
        request: Request, chosen: RunScope, limit: Annotated[int, Query(ge=1, le=50)] = 10
    ) -> IssueSuggestionsView:
        """Issue drafts for the top recurring failures; drafts only, nothing is created (docs/issues.md)."""
        # The draft lives on GitHub, so its dashboard links must be absolute: this site's address
        return current().issue_suggestions(chosen, limit, str(request.base_url))

    @app.get("/api/repository-trends", tags=["history"])
    def repository_trends(
        chosen: RunScope, days: Annotated[int, Query(ge=1, le=90)] = 7
    ) -> RepositoryTrendsView:
        """Each repository's snapshot on the newest day with runs against ``days`` earlier."""
        return current().repository_trends(chosen, days)

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
        status: Annotated[
            str | None, Query(max_length=40, description="incomplete, success, failure, ...")
        ] = None,
        workflow: Annotated[str | None, Query(max_length=200)] = None,
        pipeline: Annotated[str | None, Query(max_length=200, description="one pipeline id")] = None,
    ) -> PipelinesView:
        """Pipeline executions, newest first; with ``jobs``, the ones missing a job are incomplete."""
        expected = [job.strip() for job in (jobs or "").split(",") if job.strip()]
        return current().pipelines(chosen, expected, status=status, workflow=workflow, pipeline=pipeline)

    @app.get("/api/collection", tags=["executions"])
    def collection() -> CollectionHealthView:
        """Per repository: last collection, freshness against the expected schedule, problems."""
        return current().collection_health(expected_hours=collection_hours, workflow_url=collection_url)

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
