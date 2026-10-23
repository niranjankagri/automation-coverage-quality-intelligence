from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from qualityintel.dashboard.app import create_app
from qualityintel.models.enums import Outcome
from qualityintel.models.results import PipelineJob, RunContext
from qualityintel.traceability.report import RunFilters
from qualityintel.workspace import Scope, Workspace

from .traceability.helpers import catalog, result, run

pytestmark = pytest.mark.unit


def execution_workspace() -> Workspace:
    """History with repeated tests, missing/zero durations, an undated run and two repositories."""
    first = run(
        result("A", duration_seconds=2, suite="checkout"),
        result("B", Outcome.ERROR, suite="login"),
        browser="chrome",
        day=18,
    )
    second = run(
        result("A", Outcome.FAILED, duration_seconds=6, suite="checkout"),
        result("C", Outcome.SKIPPED, duration_seconds=0, suite="login"),
        browser="chrome",
        day=19,
    )
    other = run(result("A", duration_seconds=100, suite="checkout"), browser="firefox", day=19)
    unknown = run(result("U", Outcome.ERROR), day=None)
    pipeline = PipelineJob(pipeline_id="p1", job="ui", repository="owner/one")
    return Workspace(
        catalog([], []),
        [
            first.model_copy(update={"pipeline": pipeline}),
            second.model_copy(update={"pipeline": pipeline}),
            other.model_copy(update={"pipeline": pipeline.model_copy(update={"repository": "owner/two"})}),
            unknown,
        ],
    )


def test_history_counts_and_duration_denominators() -> None:
    """Every result counts once; average uses timed records only and never exceeds maximum."""
    d = execution_workspace().execution_dashboard()
    assert d.executions == 6
    assert d.counts == {Outcome.PASSED: 2, Outcome.FAILED: 1, Outcome.ERROR: 2, Outcome.SKIPPED: 1}
    assert sum(p for p in d.percentages.values() if p is not None) == pytest.approx(100)
    assert d.recorded_duration_seconds == 108
    assert d.timed_executions == 4  # includes the recorded zero
    assert d.undated_executions == 1
    assert sum(sum(day.counts.values()) for day in d.daily) == 5
    assert [r.average_seconds for r in d.slowest] == [100, 4, 0]
    assert d.slowest[1].max_seconds == 6
    assert d.slowest[1].executions == 2
    assert d.failures[0].repository == "owner/one"
    assert d.unique_tests == 5  # repository + result key, independent of repeat executions


def test_scope_and_suite_apply_to_all_analytics() -> None:
    """Repository/browser/date and suite filters constrain totals, charts and rankings together."""
    w = execution_workspace()
    scope = Scope(
        run_filters=RunFilters(repositories=frozenset({"owner/one"}), browsers=frozenset({"chrome"}))
    )
    d = w.execution_dashboard(scope, suite="checkout")
    assert d.executions == 2
    assert d.runs == 2
    assert d.suites == ("checkout", "login")
    assert d.recorded_duration_seconds == 8
    assert len(d.slowest) == 1
    assert w.execution_dashboard(scope, suite="absent").executions == 0
    dated = w.execution_dashboard(Scope(run_filters=RunFilters(since=datetime(2026, 10, 19).date())))
    assert dated.executions == 3
    assert dated.undated_executions == 0


def test_empty_and_unknown_durations_are_not_zero() -> None:
    """Empty history has no rate or duration; results without timing are not ranked as fast tests."""
    empty = Workspace(catalog([], []), []).execution_dashboard()
    assert empty.executions == 0
    assert set(empty.percentages.values()) == {None}
    assert empty.recorded_duration_seconds is None
    assert empty.slowest == ()
    assert empty.daily == ()
    d = Workspace(catalog([], []), [run(result("unknown"))]).execution_dashboard()
    assert d.recorded_duration_seconds is None
    assert d.timed_executions == 0
    assert not d.slowest


def test_dates_use_utc_and_limits_are_bounded() -> None:
    """Offset timestamps group under their UTC day, and no unbounded ranking can be requested."""
    source = run(result("A"), day=19).model_copy(
        update={"started_at": datetime(2026, 10, 19, 1, tzinfo=timezone(timedelta(hours=5, minutes=30)))}
    )
    w = Workspace(catalog([], []), [source])
    assert str(w.execution_dashboard().daily[0].day) == "2026-10-18"
    assert len(execution_workspace().execution_dashboard(limit=1).slowest) == 1
    for limit in (0, 101):
        with pytest.raises(ValueError, match="limit"):
            w.execution_dashboard(limit=limit)


def test_execution_dashboard_api_filters_and_validation() -> None:
    """The JSON endpoint exposes historical data with validated shared scope and ranking size."""
    with TestClient(create_app(execution_workspace())) as client:
        response = client.get("/api/executions?repository=owner/one&suite=checkout&limit=1")
        assert response.status_code == 200
        body = response.json()
        assert body["executions"] == 2
        assert body["counts"]["failed"] == 1
        assert len(body["slowest"]) == 1
        assert body["slowest"][0]["average_seconds"] == 4
        assert client.get("/api/executions?limit=101").status_code == 422
        assert client.get("/api/executions?since=2026-10-20&until=2026-10-19").status_code == 422


@pytest.mark.parametrize(
    ("job", "framework", "browser", "expected"),
    [
        ("api", "pytest", "chrome", "api"),
        ("checks-api-local", "node-test", None, "api"),
        ("unit", "testng", None, "unit"),
        ("checks-service-unit", "node-test", None, "unit"),
        ("component", "cypress", "electron", "component"),
        ("ui-chrome", "testng", "chrome", "ui"),
        ("e2e-firefox", "pytest", "firefox", "ui"),
        ("smoke-edge", "testng", "edge", "ui"),
        ("visual", "playwright", "chromium", "visual"),
        ("a11y-chromium", "playwright", "chromium", "accessibility"),
        ("android", "testng", None, "mobile"),
        ("consumer", "node-test", None, "contract"),
        ("integration", "junit5", None, "integration"),
        ("smoke", "k6", None, "performance"),
        ("smoke", "pytest", None, "other"),
        ("ambiguous", "playwright", "chromium", "other"),
    ],
)
def test_navigation_family_uses_explicit_job_conventions(
    job: str, framework: str, browser: str | None, expected: str
) -> None:
    """A browser must never turn an API or ambiguous job into a UI classification."""
    from qualityintel.workspace import execution_kind

    source = run(result("A")).model_copy(
        update={
            "pipeline": PipelineJob(pipeline_id="p", repository="owner/repo", job=job),
            "context": RunContext(framework=framework, browser=browser),
        }
    )
    assert execution_kind(source) == expected


def test_navigation_options_and_family_filter_share_the_same_evidence() -> None:
    """Every result has one family, including unassigned runs; family totals reconcile."""
    w = execution_workspace()
    options = w.execution_options()
    assert sum(o.executions for o in options) == w.execution_dashboard().executions
    assert {o.kind for o in options} == {"ui", "other"}
    assert w.execution_dashboard(kind="ui").executions == 5
    assert w.execution_dashboard(kind="other").counts[Outcome.ERROR] == 1
    assert w.execution_dashboard(kind="api").executions == 0
    with TestClient(create_app(w)) as client:
        assert client.get("/api/execution-options").status_code == 200
        assert client.get("/api/executions?kind=other").json()["executions"] == 1
        assert (
            client.get("/api/executions?kind=ui&repository=owner/two&browser=chrome").json()["executions"]
            == 0
        )
        assert (
            client.get("/api/executions?kind=ui&repository=owner/two&browser=firefox").json()["executions"]
            == 1
        )
        assert client.get("/api/executions?kind=unknown").json()["executions"] == 0


def test_dashboard_assets_revalidate_after_deployment() -> None:
    """The page and unversioned bundle cannot silently remain fresh across a deployment."""
    with TestClient(create_app(execution_workspace())) as client:
        for path in ("/", "/static/app.js", "/static/style.css", "/api/execution-options"):
            response = client.get(path)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-cache"
