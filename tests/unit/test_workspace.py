from pathlib import Path

import pytest

from qualityintel.models.enums import Outcome
from qualityintel.traceability.coverage import Filters
from qualityintel.traceability.report import RunFilters
from qualityintel.workspace import Scope, Workspace

from .traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit


@pytest.fixture
def workspace() -> Workspace:
    """Two requirements, three cases, two days of runs on two browsers.

    R1 critical: A (automated, ui), M (manual)
    R2 high:     B (automated, api)
    18 Oct firefox: A passed, B failed
    19 Oct firefox: A failed (timeout), B passed, X passed (unmatched)
    19 Oct chrome:  A passed
    """
    cat = catalog(
        [
            req("R1", criticality="critical", feature="Checkout"),
            req("R2", criticality="high", feature="Search"),
        ],
        [
            case("A", "R1", test_type="ui", framework="playwright"),
            case("M", "R1", status="manual"),
            case("B", "R2", test_type="api", framework="pytest"),
        ],
    )
    return Workspace(
        cat,
        [
            run(result("A"), result("B", Outcome.FAILED), day=18, browser="firefox", build="b1"),
            run(
                result("A", Outcome.FAILED, failure={"message": "timeout"}),
                result("B"),
                result("X"),
                day=19,
                browser="firefox",
                build="b2",
            ),
            run(result("A"), day=19, hour=10, browser="chrome", build="b2"),
        ],
    )


def test_summary_separates_coverage_from_pass_rate(workspace: Workspace) -> None:
    """Coverage comes from the catalog, pass rate from the snapshot (latest run per browser)."""
    summary = workspace.summary()

    assert summary.requirements_total == 2
    assert summary.requirement_coverage.text == "100.0 % (2/2)"
    assert summary.automation_coverage.text == "66.7 % (2/3)"
    # snapshot = 19 Oct firefox (A failed, B passed, X passed) + 19 Oct chrome (A passed)
    assert summary.pass_rate.text == "75.0 % (3/4)"
    assert summary.outcome_counts[Outcome.FAILED] == 1
    assert [r.id for r in summary.failing_requirements] == ["R1"]
    assert summary.failing_critical == ("R1",)
    assert summary.unmatched_results == 1
    assert summary.uncovered_critical == ()


def test_requirement_rows_and_status_filter(workspace: Workspace) -> None:
    """Rows carry coverage and execution status; the status filter drills down."""
    rows = workspace.requirements()

    assert [(r.id, r.coverage_status, r.execution_status) for r in rows] == [
        ("R1", "automated", "failing"),
        ("R2", "automated", "passing"),
    ]
    assert [r.id for r in workspace.requirements(status="failing")] == ["R1"]
    assert rows[0].test_cases == 2
    assert rows[0].automated_test_cases == 1


def test_requirement_detail_lists_cases_with_latest_executions(workspace: Workspace) -> None:
    """R1: case A failing on firefox and passing on chrome; manual M not automated."""
    detail = workspace.requirement("R1")

    assert [(c.id, c.execution_status) for c in detail.test_cases] == [
        ("A", "failing"),
        ("M", "not automated"),
    ]
    executions = detail.test_cases[0].executions
    assert sorted((e.context.browser, e.outcome) for e in executions) == [
        ("chrome", Outcome.PASSED),
        ("firefox", Outcome.FAILED),
    ]


def test_unknown_ids_raise_key_error(workspace: Workspace) -> None:
    """The API turns these into 404 answers."""
    with pytest.raises(KeyError):
        workspace.requirement("R9")
    with pytest.raises(KeyError):
        workspace.run("0" * 64)
    with pytest.raises(KeyError):
        workspace.test_history("suite::never-ran")


def test_tests_list_counts_every_execution_and_puts_failures_first(workspace: Workspace) -> None:
    """A ran 3 times (1 failure), B twice (1 failure), X once; failing tests sort first."""
    rows = {r.key: r for r in workspace.tests()}

    assert (rows["suite::A"].executions, rows["suite::A"].failed) == (3, 1)
    assert rows["suite::A"].latest_outcome is Outcome.PASSED  # chrome ran last
    assert rows["suite::A"].last_failure == "timeout"
    assert rows["suite::A"].test_cases == ("A",)
    assert rows["suite::X"].test_cases == ()
    assert [r.key for r in workspace.tests()][-1] == "suite::X"
    assert [r.key for r in workspace.tests(outcome=Outcome.PASSED)] == ["suite::A", "suite::B", "suite::X"]


def test_test_history_is_newest_first(workspace: Workspace) -> None:
    """History of A: chrome 19th, firefox 19th, firefox 18th."""
    history = workspace.test_history("suite::A")

    assert [(e.context.browser, e.context.build, e.outcome) for e in history.executions] == [
        ("chrome", "b2", Outcome.PASSED),
        ("firefox", "b2", Outcome.FAILED),
        ("firefox", "b1", Outcome.PASSED),
    ]


def test_run_filters_apply_to_every_view(workspace: Workspace) -> None:
    """Only chrome: one run, A passing, B not run."""
    scope = Scope(run_filters=RunFilters(browsers=frozenset({"chrome"})))

    assert len(workspace.run_list(scope)) == 1
    assert workspace.summary(scope).requirement_status_counts == {"passing": 1, "not run": 1}
    assert [r.key for r in workspace.tests(scope)] == ["suite::A"]


def test_catalog_filters_change_the_requirement_rows(workspace: Workspace) -> None:
    """Test type api: R1 has no case of that type, so it shows 'no tests' in this scope."""
    scope = Scope(filters=Filters(test_types=frozenset({"api"})))

    rows = {r.id: r for r in workspace.requirements(scope)}

    assert rows["R1"].coverage_status == "no tests"
    assert rows["R2"].coverage_status == "automated"


def test_run_detail_lists_failures_first(workspace: Workspace) -> None:
    """In a run, errors and failures come before passes."""
    newest_firefox = next(r for r in workspace.run_list() if r.context.browser == "firefox")

    detail = workspace.run(newest_firefox.run_id)

    assert [e.name for e in detail.executions] == ["A", "B", "X"]
    assert detail.run.pass_rate.text == "66.7 % (2/3)"


def test_facets_list_values_present_in_the_data(workspace: Workspace) -> None:
    """Drop-down values come from the catalog and runs, never a fixed list."""
    facets = workspace.facets()

    assert facets.features == ("Checkout", "Search")
    assert facets.criticalities == ("critical", "high")
    assert facets.test_types == ("api", "ui", "unspecified")
    assert facets.frameworks == ("playwright", "pytest")
    assert facets.browsers == ("chrome", "firefox")


def test_empty_workspace_has_not_applicable_metrics() -> None:
    """No runs: pass rate n/a, every view still answers."""
    empty = Workspace(catalog([req("R1")], []), [])

    summary = empty.summary()

    assert summary.pass_rate.percent is None
    assert summary.snapshot == ()
    assert empty.tests() == ()
    assert empty.run_list() == ()


def test_load_reads_catalog_and_results(tmp_path: Path) -> None:
    """Workspace.load combines the catalog loader and the batch importer."""
    (tmp_path / "catalog.toml").write_text('[[requirement]]\nid = "R1"\ntitle = "t"\n', encoding="utf-8")
    (tmp_path / "junit.xml").write_text(
        '<testsuite name="s"><testcase name="t"/></testsuite>', encoding="utf-8"
    )

    loaded, batch = Workspace.load(tmp_path / "catalog.toml", [tmp_path / "junit.xml"])

    assert batch.complete
    assert len(loaded.runs) == 1
