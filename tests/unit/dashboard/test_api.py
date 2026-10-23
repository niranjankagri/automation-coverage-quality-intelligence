"""The JSON API, through FastAPI's TestClient (no server, no browser)."""

import base64
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from qualityintel.dashboard.app import CONTENT_SECURITY_POLICY, LoginThrottle, create_app
from qualityintel.workspace import Workspace

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[3] / "samples"
NO_RUN = "0" * 64


@pytest.fixture(scope="module")
def client() -> TestClient:
    """The sample workspace behind a test client."""
    workspace, batch = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    assert batch.complete
    return TestClient(create_app(workspace))


def test_health_reports_the_loaded_data(client: TestClient) -> None:
    """42 requirements and 43 runs are loaded."""
    body = client.get("/api/health").json()

    assert body["status"] == "ok"
    assert (body["requirements"], body["runs"]) == (42, 43)


def test_summary_numbers_match_the_traceability_engine(client: TestClient) -> None:
    """Same values as `qi coverage` (checked independently in tests/integration)."""
    body = client.get("/api/summary").json()

    assert body["requirement_coverage"]["text"] == "90.5 % (38/42)"
    assert body["automation_coverage"]["text"] == "86.0 % (37/43)"
    assert body["automated_requirement_coverage"]["text"] == "76.2 % (32/42)"
    assert [r["id"] for r in body["uncovered_critical"]] == ["SHOP-008", "ADMIN-012"]
    assert body["pass_rate"]["text"] == "100.0 % (221/221)"


def test_filters_are_repeatable_query_parameters(client: TestClient) -> None:
    """Two criticalities at once (13 critical + 16 high); the scope shrinks accordingly."""
    body = client.get("/api/summary?criticality=critical&criticality=high").json()

    assert body["requirements_total"] == 29


def test_requirement_status_drill_down(client: TestClient) -> None:
    """status=no tests lists exactly the four requirements without tests."""
    rows = client.get("/api/requirements", params={"status": "no tests"}).json()

    assert [r["id"] for r in rows] == ["NOTES-012", "SHOP-010", "ADMIN-010", "ADMIN-012"]


def test_requirement_evidence_filters_are_additive_and_exact(client: TestClient) -> None:
    """Observed, coverage and execution filters describe separate fields in the requirement rows."""
    all_rows = client.get("/api/requirements").json()
    observed = client.get("/api/requirements", params={"observed": "true"}).json()
    unobserved = client.get("/api/requirements", params={"observed": "false"}).json()
    uncovered = client.get("/api/requirements", params={"coverage_status": "no tests"}).json()
    passing = client.get("/api/requirements", params={"execution_status": "passing"}).json()

    assert len(observed) + len(unobserved) == len(all_rows) == 42
    assert all(row["observed"] for row in observed)
    assert all(not row["observed"] for row in unobserved)
    assert all(row["coverage_status"] == "no tests" for row in uncovered)
    assert all(row["execution_status"] == "passing" for row in passing)
    assert client.get("/api/requirements?coverage_status=passing").status_code == 422


def test_requirement_detail_and_404(client: TestClient) -> None:
    """A known id gives its test cases; an unknown id gives 404 with a message."""
    detail = client.get("/api/requirements/SHOP-006").json()
    missing = client.get("/api/requirements/NOPE-1")

    assert [c["id"] for c in detail["test_cases"]] == ["TC-SHOP-CHECKOUT"]
    assert detail["requirement"]["description"].startswith("Logged-in customers can order")  # from the CSV
    assert detail["test_cases"][0]["execution_status"] == "passing"
    assert missing.status_code == 404
    assert missing.json()["detail"] == "unknown requirement 'NOPE-1'"


def test_test_history_by_key_in_the_query(client: TestClient) -> None:
    """The Selenium test that failed on 13 Oct shows that failure in its history."""
    key = "com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer"

    history = client.get("/api/tests/history", params={"key": key}).json()

    outcomes = [e["outcome"] for e in history["executions"]]
    assert len(outcomes) == 13
    assert outcomes.count("failed") == 1
    assert history["test_cases"] == ["TC-ADMIN-CUSTOMERS-UI"]
    assert client.get("/api/tests/history", params={"key": "nope"}).status_code == 404


def test_tests_list_puts_failing_tests_first(client: TestClient) -> None:
    """Tests with failures or errors anywhere in the history come first."""
    rows = client.get("/api/tests").json()

    assert rows[0]["failed"] + rows[0]["errors"] > 0
    assert len(rows) == 221


def test_runs_and_run_detail(client: TestClient) -> None:
    """Runs newest first; a run detail lists failures before passes; unknown run is 404."""
    runs = client.get("/api/runs", params={"framework": "playwright"}).json()
    attempt1 = next(r for r in runs if r["source"].endswith("39229363499-attempt1.xml"))
    detail = client.get(f"/api/runs/{attempt1['run_id']}").json()

    assert len(runs) == 5
    assert detail["executions"][0]["outcome"] == "failed"
    assert client.get(f"/api/runs/{NO_RUN}").status_code == 404


@pytest.mark.parametrize(
    ("path", "query"),
    [
        ("/api/summary", "criticality=urgent"),
        ("/api/summary", "test_type=manual"),
        ("/api/requirements", "status=done"),
        ("/api/tests", "outcome=green"),
    ],
)
def test_impossible_filter_values_are_rejected(client: TestClient, path: str, query: str) -> None:
    """A value that can never match is a 422 with an explanation, not an empty answer."""
    response = client.get(f"{path}?{query}")

    assert response.status_code == 422


def test_unknown_but_possible_values_give_an_empty_scope(client: TestClient) -> None:
    """A browser nobody used is a valid question with an empty answer (n/a pass rate)."""
    body = client.get("/api/summary?browser=safari").json()

    assert body["snapshot"] == []
    assert body["pass_rate"]["percent"] is None


def test_front_end_is_served_with_a_strict_content_security_policy(client: TestClient) -> None:
    """The page, its script and stylesheet come from this server; no inline code is allowed."""
    page = client.get("/")
    script = client.get("/static/app.js")

    assert page.status_code == 200
    assert '<script src="/static/app.js" defer></script>' in page.text
    assert page.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert script.headers["x-content-type-options"] == "nosniff"
    assert "unsafe-inline" not in CONTENT_SECURITY_POLICY


def test_openapi_documentation_lists_every_route(client: TestClient) -> None:
    """/docs is generated from the routes, so it cannot drift from the API."""
    paths = set(client.get("/openapi.json").json()["paths"])

    assert paths == {
        "/api/health",
        "/api/status",
        "/api/search",
        "/api/attention",
        "/api/tests/summary",
        "/api/compare/summary",
        "/api/facets",
        "/api/summary",
        "/api/readiness",
        "/api/requirements",
        "/api/requirements/matrix",
        "/api/requirements/{requirement_id}",
        "/api/tests",
        "/api/tests/history",
        "/api/runs",
        "/api/pipelines",
        "/api/collection",
        "/api/runs/{run_id}",
        "/api/builds",
        "/api/compare",
        "/api/regressions",
        "/api/stability",
        "/api/trends",
    }


def test_stability_lists_the_real_flaky_candidates(client: TestClient) -> None:
    """Four flaky candidates with reasons; stable tests are left out unless asked for."""
    body = client.get("/api/stability").json()

    assert body["status_counts"] == {"flaky candidate": 4, "stable": 217}
    assert len(body["rows"]) == 4
    edits = next(r for r in body["rows"] if r["key"].endswith("adminEditsACustomer"))
    assert edits["context"] == "testng / ci / firefox / linux"
    assert edits["test_cases"] == ["TC-ADMIN-CUSTOMERS-UI"]
    assert "passed and failed on the same build (f5a40d5)" in edits["reasons"]
    assert len(client.get("/api/stability?include_stable=true").json()["rows"]) == 221


def test_stability_window_and_trends(client: TestClient) -> None:
    """A window of 3 forgets the 13 Oct failure; trends have one series per context."""
    body = client.get("/api/stability", params={"window": 3}).json()

    assert body["window"] == 3
    assert not any(r["key"].endswith("adminEditsACustomer") for r in body["rows"])
    assert len(body["trends"]) == 5
    assert len(body["trends"]["testng / ci / firefox / linux"]) == 13
    assert client.get("/api/stability", params={"window": 0}).status_code == 422


@pytest.mark.parametrize(
    "header",
    [
        None,
        "Basic " + base64.b64encode(b"qi:wrong password!").decode(),
        "Basic " + base64.b64encode(b"other:correct horse battery").decode(),
        "Basic not-base64!!",
        "Bearer correct horse battery",
    ],
    ids=["none", "wrong-password", "wrong-user", "malformed", "other-scheme"],
)
def test_login_is_required_for_every_path_when_a_password_is_set(header: str | None) -> None:
    """Pages, static files, API and docs all answer 401 with a Basic challenge."""
    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [])
    client = TestClient(create_app(workspace, ("qi", "correct horse battery")))
    headers = {"Authorization": header} if header else {}

    for path in ("/", "/static/app.js", "/api/health", "/api/summary", "/docs", "/openapi.json"):
        response = client.get(path, headers=headers)
        assert response.status_code == 401, path
        assert response.headers["WWW-Authenticate"].startswith("Basic ")


def test_the_right_login_opens_everything() -> None:
    """With the credentials every route answers as without a password."""
    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [])
    client = TestClient(create_app(workspace, ("qi", "correct horse battery")))

    for path in ("/", "/static/app.js", "/api/health", "/api/summary"):
        assert client.get(path, auth=("qi", "correct horse battery")).status_code == 200, path


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_the_api_accepts_no_writes(client: TestClient, method: str) -> None:
    """Read-only: no route takes a body or changes anything, so there is nothing to upload into."""
    for path in ("/api/summary", "/api/runs", "/api/pipelines", "/"):
        assert client.request(method, path).status_code == 405, (method, path)


def test_status_describes_the_data_and_its_freshness(client: TestClient) -> None:
    """Fixed data: loaded once, never refreshed, nothing stale; latest run of the samples."""
    body = client.get("/api/status").json()

    assert body["version"] == "fixed"
    assert body["refresh_seconds"] == 0
    assert body["stale"] is False
    assert body["last_error"] is None
    assert body["latest_run_started_at"].startswith("2026-10-19")


def test_status_check_reloads_live_data_and_reports_failures(tmp_path: Path) -> None:
    """check=true picks up a new run; a broken database leaves the data and sets stale."""
    import os
    import shutil

    from qualityintel.history.store import HistoryStore
    from qualityintel.live import MIN_FORCED_SECONDS, LiveData, Sources, load_snapshot

    shutil.copy(SAMPLES / "catalog.toml", tmp_path / "catalog.toml")
    shutil.copy(SAMPLES / "requirements.toml", tmp_path / "requirements.toml")
    database = tmp_path / "h.db"
    runs = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results" / "pytest-notes-api"])[0].runs
    with HistoryStore(database) as store:
        store.add(runs[0])
    sources = Sources(tmp_path / "catalog.toml", database)
    now = [0.0]
    live = LiveData(load_snapshot(sources), sources, interval_seconds=30, clock=lambda: now[0])
    client = TestClient(create_app(live))
    before = client.get("/api/status").json()["version"]

    with HistoryStore(database) as store:
        store.add(runs[1])
    os.utime(database, (1e9, 2e9))
    now[0] += MIN_FORCED_SECONDS + 1
    after = client.get("/api/status", params={"check": "true"}).json()
    assert after["version"] != before
    assert client.get("/api/health").json()["runs"] == 2

    database.write_bytes(b"garbage" * 100)
    now[0] += MIN_FORCED_SECONDS + 1
    broken = client.get("/api/status", params={"check": "true"}).json()
    assert broken["stale"] is True
    assert broken["version"] == after["version"]
    assert client.get("/api/health").json()["runs"] == 2  # the last good data is still served


@pytest.mark.parametrize(
    ("gate", "state", "reason"),
    [
        (None, "unknown", "no release gate is configured"),
        ("release.toml", "blocked", "rule failed: critical requirements without automation"),
        ("nightly.toml", "at risk", "4 flaky candidate(s) in the scope"),
    ],
)
def test_readiness_on_the_real_samples(gate: str | None, state: str, reason: str) -> None:
    """No gate: unknown; the release gate blocks; the nightly passes but the flaky candidates put it at risk."""
    from qualityintel.gates.config import load_gate_config

    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    workspace.gate = load_gate_config(SAMPLES / "gates" / gate) if gate else None
    body = TestClient(create_app(workspace)).get("/api/readiness").json()

    assert body["state"] == state
    assert any(r.startswith(reason) for r in body["reasons"]), body["reasons"]
    assert body["executions"] == 221
    assert body["pass_rate"]["text"] == "100.0 % (221/221)"
    assert body["requirement_coverage"]["text"] == "90.5 % (38/42)"
    assert body["critical_without_automation"] == 2
    assert body["flaky_candidates"] == 4


def test_readiness_follows_the_chosen_scope(client: TestClient) -> None:
    """Numbers are for the scope in the query, like every other endpoint."""
    body = client.get("/api/readiness", params={"framework": "robot-framework"}).json()

    assert body["executions"] == 30


def test_builds_are_listed_in_the_order_they_first_ran(client: TestClient) -> None:
    """The comparison selectors: builds by first run; the build filter itself is ignored."""
    assert client.get("/api/builds", params={"framework": "testng"}).json() == [
        "f5a40d5",
        "1d03232",
        "e30ab76",
    ]
    assert (
        client.get("/api/builds", params={"framework": "testng", "build": "e30ab76"}).json()[0] == "f5a40d5"
    )


def test_comparing_two_real_testng_builds(client: TestClient) -> None:
    """Same suite (TestNG on Firefox) in both: compared test by test; 10 tests got slower."""
    body = client.get(
        "/api/compare", params={"framework": "testng", "base": "f5a40d5", "head": "1d03232"}
    ).json()

    assert body["comparable"] is True
    assert body["compared_contexts"] == ["testng/ci/firefox/linux"]
    assert body["category_counts"] == {"slower": 10}
    assert all(c["head_seconds"] > c["base_seconds"] for c in body["changes"])
    assert body["base"]["pass_rate"]["text"] == "100.0 % (121/121)"


def test_builds_of_different_suites_are_not_compared(client: TestClient) -> None:
    """A Robot build and a TestNG build share no suite: listed, nothing counted as a change."""
    body = client.get("/api/compare", params={"base": "b378a19", "head": "e30ab76"}).json()

    assert body["comparable"] is False
    assert body["changes"] == []
    assert body["only_in_base"]
    assert body["only_in_head"]
    assert any("share no suite" in n for n in body["notes"])


def test_latest_regressions_on_the_samples_compare_each_suite_with_its_previous_build(
    client: TestClient,
) -> None:
    """Four suites ran in two or more builds (none newly fails there); one ran in a single build."""
    body = client.get("/api/regressions").json()

    assert (body["compared"], body["single_build"], body["regressions"]) == (4, 1, [])
    assert any("branch" in note for note in body["notes"])
    # The scope applies: TestNG on Firefox is one of the four (f5a40d5 -> 1d03232 only got slower)
    testng = client.get("/api/regressions", params={"framework": "testng"}).json()
    assert (testng["compared"], testng["regressions"]) == (1, [])


def test_comparison_input_errors(client: TestClient) -> None:
    """The same build twice is a client error; an unknown build is not found."""
    assert client.get("/api/compare", params={"base": "e30ab76", "head": "e30ab76"}).status_code == 422
    assert client.get("/api/compare", params={"base": "nope", "head": "e30ab76"}).status_code == 404


def test_test_history_lists_requirements_and_counts(client: TestClient) -> None:
    """The investigation panel's data: requirements of the linked test cases, pass/fail counts."""
    key = next(t["key"] for t in client.get("/api/tests").json() if "adminEditsACustomer" in t["key"])
    body = client.get("/api/tests/history", params={"key": key}).json()

    assert (body["passed"], body["failed"]) == (12, 1)
    assert body["requirements"]
    assert body["executions"][0]["pipeline"] is None  # sample files are not pipeline runs


def test_requirement_matrix_counts_match_the_requirement_list(client: TestClient) -> None:
    """By criticality: totals add up to the 42 requirements and equal the list's own counts."""
    matrix = client.get("/api/requirements/matrix").json()
    rows = client.get("/api/requirements").json()

    assert sum(r["total"] for r in matrix["by_criticality"]) == len(rows) == 42
    critical = next(r for r in matrix["by_criticality"] if r["group"] == "critical")
    listed = [r for r in rows if r["criticality"] == "critical"]
    assert critical["total"] == len(listed) == 13
    assert critical["coverage"].get("no tests", 0) == sum(r["coverage_status"] == "no tests" for r in listed)
    assert matrix["stale_days"] == 14


def test_stale_evidence_depends_on_the_age_of_the_latest_execution() -> None:
    """Seen on 20 Oct the October samples are fresh; seen on 30 Nov the executed ones are stale."""
    from datetime import UTC, datetime

    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [SAMPLES / "results"])
    fresh = workspace.requirement_matrix(now=datetime(2026, 10, 20, tzinfo=UTC))
    later = workspace.requirement_matrix(now=datetime(2026, 11, 30, tzinfo=UTC))
    executed = sum(
        1 for r in TestClient(create_app(workspace)).get("/api/requirements").json() if r["last_executed_at"]
    )

    assert sum(r.stale for r in fresh.by_criticality) == 0
    assert sum(r.stale for r in later.by_criticality) == executed > 0


def test_stability_rows_link_to_the_runs_behind_them(client: TestClient) -> None:
    """Every flaky candidate names its last failing and passing run and the builds involved."""
    rows = client.get("/api/stability").json()["rows"]
    flaky = [r for r in rows if r["status"] == "flaky candidate"]
    run_ids = {r["run_id"] for r in client.get("/api/runs").json()}

    assert len(flaky) == 4
    for row in flaky:
        assert row["last_failing_run_id"] in run_ids
        assert row["last_passing_run_id"] in run_ids
        assert row["last_failed_at"] is not None
        assert row["affected_builds"]


def test_too_many_wrong_logins_lock_the_address_out_for_a_while() -> None:
    """After 10 wrong logins in 5 minutes even the right one answers 429 with Retry-After."""
    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [])
    client = TestClient(create_app(workspace, ("qi", "correct horse battery")))

    assert client.get("/api/health").status_code == 401  # no credentials yet: not counted
    for _ in range(10):
        assert client.get("/api/health", auth=("qi", "guess guess guess")).status_code == 401
    locked = client.get("/api/health", auth=("qi", "correct horse battery"))

    assert locked.status_code == 429
    assert 1 <= int(locked.headers["Retry-After"]) <= 300


def test_the_throttle_forgets_old_failures_and_stays_bounded() -> None:
    """Failures leave the window after 5 minutes; at most max_clients addresses are tracked."""
    throttle = LoginThrottle(limit=2, window_seconds=300, max_clients=3)
    throttle.failed("a", 0)
    throttle.failed("a", 1)

    assert throttle.retry_after("a", 2) == 298  # until the first failure leaves the window
    assert throttle.retry_after("a", 301) == 0
    for moment in (310, 320, 330):
        throttle.failed("a", moment)
    # Three failures in the window (310, 320, 330), limit 2: allowed again when 320 leaves it
    assert throttle.retry_after("a", 340) == 280
    for client in ("b", "c", "d", "e"):
        throttle.failed(client, 400)
    assert len(throttle._failures) == 3


def test_api_answers_are_not_kept_by_caches_and_https_gets_hsts() -> None:
    """With a login: private, no-store; without: revalidate. HSTS only over https."""
    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [])
    private = TestClient(
        create_app(workspace, ("qi", "correct horse battery")), base_url="https://qi.example"
    )
    public = TestClient(create_app(workspace))

    secured = private.get("/api/health", auth=("qi", "correct horse battery"))
    assert secured.headers["Cache-Control"] == "private, no-store"
    assert secured.headers["Strict-Transport-Security"] == "max-age=31536000"
    plain = public.get("/api/health")
    assert plain.headers["Cache-Control"] == "no-cache"
    assert "Strict-Transport-Security" not in plain.headers
    assert "Cross-Origin-Opener-Policy" not in plain.headers  # see docs/security.md


def test_the_access_log_is_one_json_line_per_request_without_queries_or_logins(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Method, path, status and duration; never the query string or the Authorization header."""
    import json

    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [])
    client = TestClient(create_app(workspace, ("qi", "correct horse battery"), access_log=True))
    capsys.readouterr()

    client.get("/api/runs", params={"framework": "secret-team-name"}, auth=("qi", "correct horse battery"))
    client.get("/api/health", auth=("qi", "wrong password!!"))

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [(e["method"], e["path"], e["status"]) for e in lines] == [
        ("GET", "/api/runs", 200),
        ("GET", "/api/health", 401),
    ]
    assert all(set(e) == {"time", "method", "path", "status", "ms"} for e in lines)


def test_requirements_have_owners_to_filter_and_group_by(client: TestClient) -> None:
    """Owner: a facet, a filter that narrows every view, a matrix grouping; counts add up to 42."""
    owners = client.get("/api/facets").json()["owners"]
    by_owner = {r["group"]: r["total"] for r in client.get("/api/requirements/matrix").json()["by_owner"]}
    admin = client.get("/api/requirements", params={"owner": "Admin team"}).json()
    summary = client.get("/api/summary", params={"owner": "Admin team"}).json()

    assert owners == ["Admin team", "Notes API team", "Storefront team", "Toolshop team"]
    assert sum(by_owner.values()) == 42
    assert len(admin) == by_owner["Admin team"] == 12
    assert {r["owner"] for r in admin} == {"Admin team"}
    assert summary["requirements_total"] == 12
    assert client.get("/api/requirements/SHOP-006").json()["requirement"]["owner"] == "Toolshop team"


def test_health_names_the_deployed_commit_and_the_catalog_notice(monkeypatch: pytest.MonkeyPatch) -> None:
    """Render's RENDER_GIT_COMMIT (or QI_BUILD_COMMIT) is reported; anything not a commit id is not."""
    workspace, _ = Workspace.load(SAMPLES / "catalog.toml", [])
    client = TestClient(create_app(workspace))
    monkeypatch.setenv("RENDER_GIT_COMMIT", "7A429BB0123456789abcdef0123456789abcdef0")

    body = client.get("/api/health").json()
    assert body["commit"] == "7a429bb0123456789abcdef0123456789abcdef0"
    assert "synthetic sample catalog" in body["catalog_notice"]
    monkeypatch.setenv("RENDER_GIT_COMMIT", "<script>")
    assert client.get("/api/health").json()["commit"] is None


def test_search_groups_results_links_them_and_validates_input(client: TestClient) -> None:
    """Grouped with counts; every hit leads to a page; too short, too long and bad limits are 422."""
    body = client.get("/api/search", params={"q": "checkout"}).json()

    assert body["query"] == "checkout"
    assert body["total"] == sum(body["counts"].values()) > 0
    for kind, hits in body["groups"].items():
        assert len(hits) <= body["limit"]
        assert all(hit["kind"] == kind and hit["route"].startswith("/") for hit in hits)
    refused: list[dict[str, str | int]] = [
        {"q": "x"},
        {"q": "y" * 101},
        {"q": "ab", "limit": 0},
        {"q": "ab", "limit": 51},
    ]
    for params in refused:
        assert client.get("/api/search", params=params).status_code == 422


def test_search_finds_a_requirement_by_id_and_a_test_by_its_name(client: TestClient) -> None:
    """The requirement and the test pages exist for what search returns."""
    requirement = client.get("/api/search", params={"q": "SHOP-006"}).json()["groups"]["requirement"][0]
    assert requirement["route"] == "/requirement/SHOP-006"
    assert client.get("/api/requirements/SHOP-006").status_code == 200

    test = client.get("/api/search", params={"q": "adminEditsACustomer"}).json()["groups"]["test"][0]
    history = client.get("/api/tests/history", params={"key": test["params"]["key"]})
    assert history.status_code == 200


def test_attention_agrees_with_the_pages_it_summarises(client: TestClient) -> None:
    """Flaky candidates = Stability's; critical gaps = the overview's; every finding links somewhere."""
    body = client.get("/api/attention").json()
    stability = client.get("/api/stability").json()
    summary = client.get("/api/summary").json()

    assert (
        body["counts"].get("flaky candidate", 0) == stability["status_counts"].get("flaky candidate", 0) == 4
    )
    assert body["counts"]["critical gap"] == len(summary["uncovered_critical"]) == 2
    assert body["total"] == sum(body["counts"].values()) == sum(body["states"].values())
    assert all(
        f["route"].startswith("/") and f["why"] and f["state"] in {"open", "resolved", "suspected", "unknown"}
        for f in body["findings"]
    )
    states = [f["state"] for f in body["findings"]]
    assert states == sorted(states, key=["open", "suspected", "unknown", "resolved"].index)


def test_attention_kind_filter_preserves_backend_order_and_counts(client: TestClient) -> None:
    """Finding type filtering happens before the API limit and retains its evidence fields."""
    all_findings = client.get("/api/attention").json()
    critical_gaps = client.get("/api/attention", params={"kind": "critical gap"}).json()

    assert critical_gaps["total"] == all_findings["counts"]["critical gap"] == 2
    assert critical_gaps["counts"] == {"critical gap": 2}
    assert critical_gaps["states"] == {"open": 2}
    assert all(finding["kind"] == "critical gap" for finding in critical_gaps["findings"])
    assert client.get("/api/attention?kind=severity-high").status_code == 422
