"""The dashboard in a real browser, against the sample data."""

import os
import re
from pathlib import Path

import pytest
from pages.classic import (
    AttentionPage,
    ClassicPage,
    CollectionPage,
    ComparePage,
    OverviewPage,
    PipelinesPage,
    RequirementsPage,
    RunsPage,
    StabilityPage,
    TestsPage,
    TrendsPage,
)
from playwright.sync_api import Browser, Page, Route, expect

from qualityintel.history.store import HistoryStore
from qualityintel.ingest.batch import import_pipeline
from qualityintel.live import Sources

ENGINE = os.environ.get("QI_E2E_BROWSER", "chromium")

SAMPLES = Path(__file__).parents[2] / "samples"

pytestmark = pytest.mark.e2e


def test_overview_shows_coverage_and_pass_rate_separately(page: Page) -> None:
    """Coverage numbers and the execution pass rate are different cards with their counts."""
    overview = OverviewPage(page).open()

    expect(overview.heading("Overview")).to_be_visible()
    expect(overview.card("Requirement coverage")).to_contain_text("90.5 %")
    expect(overview.card("Requirement coverage")).to_contain_text("38 of 42")
    expect(overview.card("Automation coverage")).to_contain_text("37 of 43")
    expect(overview.card("Execution pass rate")).to_contain_text("221 of 221")
    expect(overview.heading("Build comparison")).to_be_visible()
    expect(overview.change_summary()).to_be_visible()
    expect(overview.critical_requirements.get_by_role("link", name="SHOP-008")).to_be_visible()
    expect(overview.critical_requirements.get_by_role("link", name="ADMIN-012")).to_be_visible()


def test_overview_lists_gaps_by_owner_with_the_most_urgent_owner_open(page: Page) -> None:
    """Coverage gaps by owner: 10 gaps; Admin team (ADMIN-012, rank 1) is open, the others folded."""
    overview = OverviewPage(page).open()

    expect(overview.heading("Coverage gaps by owner (10)", exact=False)).to_be_visible()
    first = overview.gap_owners.first
    expect(first).to_have_attribute("open", "")
    expect(first.locator("summary")).to_have_text("Admin team: 4 gap(s), most urgent #1")
    expect(first.get_by_role("row").nth(1)).to_contain_text("ADMIN-012")
    expect(overview.gap_owners).to_have_count(4)
    expect(overview.open_gap_owners).to_have_count(1)


def test_metric_card_drills_down_to_the_requirements_behind_it(page: Page) -> None:
    """Requirement coverage card -> the four requirements without tests."""
    OverviewPage(page).open().card("Requirement coverage").click()

    requirements = RequirementsPage(page)
    expect(requirements.heading("Requirements")).to_be_visible()
    expect(requirements.requirement_rows).to_have_count(4)
    expect(requirements.status).to_have_value("no tests")


def test_filter_changes_every_number_and_stays_in_the_url(page: Page) -> None:
    """Criticality critical: 13 requirements; the filter is part of the address."""
    overview = OverviewPage(page).open()

    overview.criticality.select_option("critical")

    expect(overview.card("Requirements in scope")).to_contain_text("13")
    expect(page).to_have_url(re.compile(r"criticality=critical"))
    overview.go_to("Requirements")
    requirements = RequirementsPage(page)
    expect(requirements.requirement_rows).to_have_count(13)
    requirements.clear_filters()
    expect(requirements.requirement_rows).to_have_count(42)


def test_requirement_detail_shows_cases_and_latest_executions(page: Page) -> None:
    """SHOP-006 -> its automated checkout case with four Playwright executions."""
    requirement = ClassicPage(page).open("#/requirement/SHOP-006")

    expect(requirement.heading(re.compile("^SHOP-006"))).to_be_visible()
    expect(page.get_by_text("guests are asked to sign in at checkout.")).to_be_visible()  # description
    expect(page.get_by_text("TC-SHOP-CHECKOUT")).to_be_visible()
    expect(requirement.rows).to_have_count(4)


def test_test_history_shows_the_real_selenium_failure(page: Page) -> None:
    """The 13 Oct Firefox timeout is in the history and its message can be expanded."""
    test = TestsPage(page).open().open_test("adminEditsACustomer")

    expect(test.execution_rows).to_have_count(13)
    expect(test.failed_execution_rows).to_have_count(1)
    expect(test.expand(test.failed_execution_rows)).to_contain_text("TimeoutException")


def test_run_detail_lists_failures_first(page: Page) -> None:
    """The first Playwright attempt of 19 Oct: the failed checkout test is the first row."""
    runs = RunsPage(page).open("#/runs?framework=playwright")
    runs.open_run(re.compile("39229363499-attempt1"))

    first = runs.rows.first
    expect(first.locator(".badge")).to_have_text("failed")
    expect(first).to_contain_text("customer can order two products")


def test_empty_scope_has_an_empty_state(page: Page) -> None:
    """A browser with no runs: no snapshot table, an explanation instead."""
    overview = OverviewPage(page).open("#/coverage?browser=webkit")

    expect(page.get_by_text("No runs in this scope")).to_be_visible()
    expect(overview.card("Execution pass rate")).to_contain_text("n/a")


def test_api_error_shows_a_message_and_retry(page: Page) -> None:
    """If the API fails, the page says so and offers a retry that works once the API is back."""
    calls = {"n": 0}

    def fail_once(route: Route) -> None:
        calls["n"] += 1
        if calls["n"] == 1:
            route.fulfill(status=500, content_type="application/json", body='{"detail": "database offline"}')
        else:
            route.continue_()

    page.route("**/api/summary*", fail_once)
    overview = OverviewPage(page).open()

    expect(overview.alert).to_contain_text("500: database offline")
    overview.retry()
    expect(overview.heading("Overview")).to_be_visible()


def test_unknown_page_and_unknown_requirement_show_errors(page: Page) -> None:
    """Bad links end in a readable message, not a blank page."""
    dashboard = ClassicPage(page).open("#/nowhere")
    expect(dashboard.alert).to_contain_text("This page does not exist.")

    dashboard.open("#/requirement/NOPE-1")
    expect(dashboard.alert).to_contain_text("unknown requirement 'NOPE-1'")


@pytest.mark.parametrize("width", [390, 768])
def test_layout_fits_small_screens(page: Page, width: int) -> None:
    """Phone and tablet width: no sideways scrolling of the page; wide tables scroll inside."""
    page.set_viewport_size({"width": width, "height": 800})
    dashboard = ClassicPage(page)
    for path in (
        "#/coverage",
        "#/requirements",
        "#/tests",
        "#/runs",
        "#/stability",
        "#/trends",
    ):
        dashboard.open(path)
        expect(dashboard.view_heading).to_be_visible()
        overflow = dashboard.scroll_overflow()
        assert overflow <= 0, f"/classic/{path} scrolls sideways by {overflow}px at {width}px"


def test_keyboard_users_can_skip_to_the_content(page: Page) -> None:
    """First Tab reaches the skip link; it moves focus to the main region."""
    if ENGINE == "webkit":
        pytest.skip("WebKit, like Safari by default, moves Tab between form controls only")
    overview = OverviewPage(page).open()
    expect(overview.heading("Overview")).to_be_visible()

    page.keyboard.press("Tab")
    expect(overview.skip_link).to_be_focused()
    page.keyboard.press("Enter")
    expect(overview.main).to_be_focused()


def test_stability_page_shows_flaky_candidates_with_evidence(page: Page) -> None:
    """Four flaky candidates; each row says why; a smaller window forgets the 13 Oct failure."""
    stability = StabilityPage(page).open()

    expect(stability.heading("Stability")).to_be_visible()
    expect(stability.card("Flaky candidate")).to_contain_text("4")
    expect(stability.row_with("adminEditsACustomer")).to_contain_text(
        "passed and failed on the same build (f5a40d5)"
    )
    expect(stability.strips).to_have_count(5)

    stability.window.select_option("5")

    expect(page).to_have_url(re.compile(r"window=5"))
    expect(stability.row_with("adminEditsACustomer")).to_have_count(0)


def test_trends_page_draws_what_the_api_says(page: Page) -> None:
    """Every number in the 'Test results' table equals the API's daily counts; the jump in suites is explained."""
    trends = TrendsPage(page).open()
    expect(trends.heading("Trends")).to_be_visible()
    daily = page.request.get("/api/trends").json()["daily"]

    rows = trends.number_rows("Test results")
    expect(rows).to_have_count(len(daily))
    for i, point in enumerate(daily):
        cells = rows.nth(i).locator("td")
        expect(cells.nth(0)).to_have_text(point["day"])
        expect(cells.nth(1)).to_have_text(str(point["counts"]["passed"]))
        expect(cells.nth(2)).to_have_text(str(point["counts"]["failed"]))
    expect(trends.note).to_contain_text("the set of run contexts grows on 2026-10-09, 2026-10-13, 2026-10-17")
    expect(trends.charts).to_have_count(4 + 5)  # four daily charts, one per run context


def test_date_filter_narrows_the_trend_and_stays_in_the_url(page: Page) -> None:
    """From 13 Oct to 15 Oct: three days, filter kept in the address."""
    trends = TrendsPage(page).open()
    expect(trends.heading("Trends")).to_be_visible()

    trends.date_from.fill("2026-10-13")
    expect(page).to_have_url(re.compile(r"since=2026-10-13"))
    trends.date_to.fill("2026-10-15")

    expect(page).to_have_url(
        re.compile(r"since=2026-10-13.*until=2026-10-15|until=2026-10-15.*since=2026-10-13")
    )
    expect(trends.chart("Test results")).to_contain_text("3 days from 2026-10-13 to 2026-10-15")


def test_trends_without_runs_in_scope_say_so(page: Page) -> None:
    """A date range with no runs: no chart, an explanation."""
    trends = TrendsPage(page).open("#/trends?since=2030-01-01")

    expect(page.get_by_text("No dated runs in this scope")).to_be_visible()
    expect(trends.charts).to_have_count(0)


def test_a_late_response_for_an_older_address_is_not_shown(page: Page) -> None:
    """Two filter changes in a row; the first answer arrives last and must be ignored."""
    delayed: list[Route] = []

    def hold_first(route: Route) -> None:
        if "until=" in route.request.url or delayed:
            route.continue_()
        else:
            delayed.append(route)  # answered only after the newer request finished

    trends = TrendsPage(page).open()
    expect(trends.heading("Trends")).to_be_visible()
    page.route("**/api/trends?*", hold_first)

    trends.date_from.fill("2026-10-13")
    trends.date_to.fill("2026-10-15")
    chart = trends.chart("Test results")
    expect(chart).to_contain_text("3 days from 2026-10-13 to 2026-10-15")
    assert delayed, "the first request was not held back"
    delayed[0].continue_()
    page.wait_for_load_state("networkidle")

    expect(chart).to_contain_text("3 days from 2026-10-13 to 2026-10-15")


def test_pipelines_page_shows_the_cancelled_run_as_incomplete(pipelines_page: Page) -> None:
    """Both real pipelines; naming the five jobs marks the cancelled one, and the URL keeps them."""
    page = pipelines_page
    pipelines = PipelinesPage(page).open()
    expect(pipelines.heading("Pipelines")).to_be_visible()
    complete = pipelines.pipeline("Pipeline 39238241112")
    cancelled = pipelines.pipeline("Pipeline 38842296207")
    expect(pipelines.badge(cancelled)).to_have_text("complete")  # nothing says a job is missing yet
    expect(pipelines.note).to_contain_text("No expected jobs given")

    pipelines.expect_jobs("api, ui-chrome, ui-firefox, ui-edge, component")

    expect(page).to_have_url(re.compile(r"jobs=api"))
    expect(pipelines.badge(cancelled)).to_have_text("incomplete")
    pipelines.expand(cancelled)  # jobs and problems
    expect(pipelines.missing_jobs(cancelled)).to_contain_text("ui-firefox")
    expect(cancelled).to_contain_text("job ui-firefox reported no results")
    expect(pipelines.badge(complete)).to_have_text("complete")
    expect(complete.locator("tbody tr")).to_have_count(5)
    expect(pipelines.note).to_have_count(0)
    expect(pipelines.view).not_to_contain_text("null")  # an empty slot must not print "null"


def test_status_chips_filter_the_pipelines_and_stay_in_the_address(pipelines_page: Page) -> None:
    """With the five jobs expected: 1 incomplete, 1 complete; a chip keeps only its pipelines."""
    page = pipelines_page
    pipelines = PipelinesPage(page).open("#/pipelines?jobs=api,ui-chrome,ui-firefox,ui-edge,component")
    expect(pipelines.status_chips).to_contain_text("All (2)")

    pipelines.status_chips.get_by_role("link").filter(has_text="incomplete").click()

    expect(page).to_have_url(re.compile(r"status=incomplete"))
    expect(pipelines.pipelines).to_have_count(1)
    expect(pipelines.pipelines).to_contain_text("Pipeline 38842296207")


def test_runs_page_names_the_pipeline_job(pipelines_page: Page) -> None:
    """The run list has a pipeline / job column; a run's page repeats it."""
    runs = RunsPage(pipelines_page).open()
    row = runs.row_with("ui-firefox/ui-firefox.json")
    expect(row).to_contain_text("39238241112 / ui-firefox")

    row.get_by_role("link").click()
    expect(runs.run_meta).to_contain_text("39238241112 / ui-firefox")


def test_with_a_login_the_whole_dashboard_works_after_signing_in(browser: Browser, secured_url: str) -> None:
    """The browser sends the login with the front end's own API calls too: the data appears."""
    anonymous = browser.new_context(base_url=secured_url)
    assert anonymous.new_page().goto("/").status == 401  # type: ignore[union-attr]
    anonymous.close()

    context = browser.new_context(
        base_url=secured_url, http_credentials={"username": "qi", "password": "correct horse battery"}
    )
    overview = OverviewPage(context.new_page()).open()
    expect(overview.heading("Overview", exact=False)).to_be_visible()
    expect(overview.data_size).to_contain_text("42 requirements")
    overview.go_to("Trends")
    expect(overview.charts.first).to_be_visible()
    context.close()


def test_new_history_appears_without_a_restart_and_the_filters_stay(
    live_page: Page, live_server: tuple[str, Sources]
) -> None:
    """A run is stored while the page is open: Refresh shows it, the filtered address is kept."""
    page = live_page
    _, sources = live_server
    runs = RunsPage(page).open("#/runs?framework=pytest")
    expect(runs.rows).to_have_count(3)
    expect(runs.data_fresh).to_contain_text("Data loaded")

    assert sources.database is not None
    with HistoryStore(sources.database) as store:
        newer = import_pipeline({"api": [str(SAMPLES / "results" / "pytest-notes-api")]}, "p#2").runs[3:4]
        store.add_all(newer)
    runs.refresh()

    expect(runs.rows).to_have_count(4)
    expect(page).to_have_url(re.compile(r"#/runs\?framework=pytest$"))
    expect(runs.filter_select("framework")).to_have_value("pytest")
    expect(runs.data_stale).to_be_hidden()


def test_a_failed_refresh_keeps_the_data_and_warns(live_page: Page, live_server: tuple[str, Sources]) -> None:
    """The database becomes unreadable: the page keeps its figures and says they are stale."""
    page = live_page
    _, sources = live_server
    runs = RunsPage(page).open()
    expect(runs.rows).to_have_count(3)

    assert sources.database is not None
    sources.database.write_bytes(b"not a database" * 100)
    runs.refresh()

    expect(runs.data_stale).to_be_visible()
    expect(runs.data_stale).to_contain_text("The last refresh failed")
    expect(runs.data_stale.get_by_role("link", name="Collection page")).to_be_visible()
    page.reload()
    expect(runs.rows).to_have_count(3)  # still the last good data


def test_the_repository_selection_is_kept_across_pages_and_reloads(pipelines_page: Page) -> None:
    """Chosen once, in the address, applied on every page."""
    page = pipelines_page
    runs = RunsPage(page).open()
    runs.filter_select("repository").select_option("niranjankagri/cypress-typescript-framework")

    expect(page).to_have_url(re.compile(r"repository=niranjankagri%2Fcypress-typescript-framework"))
    expect(runs.rows).to_have_count(9)
    runs.go_to("Pipelines")
    expect(page).to_have_url(re.compile(r"#/pipelines\?.*repository="))
    page.reload()
    expect(runs.filter_select("repository")).to_have_value("niranjankagri/cypress-typescript-framework")


def test_overview_shows_the_release_status_with_its_reasons(page: Page) -> None:
    """Without a gate the status is Unknown, never Ready; the numbers are the API's."""
    overview = OverviewPage(page).open()
    expect(overview.release_status).to_contain_text("Unknown")
    expect(overview.release_status).to_contain_text("no release gate is configured")
    expect(overview.card("Test executions")).to_contain_text("221")
    expect(overview.card("Flaky candidates")).to_contain_text("4")


def test_explorer_links_to_github_and_the_collection_page_shows_health(collected_page: Page) -> None:
    """The cancelled run is incomplete with its missing artifact; links open the exact run; health is fresh."""
    pipelines = PipelinesPage(collected_page).open()
    cancelled = pipelines.pipeline("#6")
    expect(pipelines.badge(cancelled)).to_have_text("incomplete")
    pipelines.expand(cancelled)
    expect(cancelled).to_contain_text("CI concluded: cancelled")
    expect(cancelled).to_contain_text("artifact report-ui-firefox not found")
    run_link = cancelled.get_by_role("link", name="Open the workflow run on GitHub")
    expect(run_link).to_have_attribute(
        "href", "https://github.com/niranjankagri/cypress-typescript-framework/actions/runs/38842296207"
    )
    expect(run_link).to_have_attribute("rel", "noopener noreferrer")

    pipelines.go_to("Collection")
    collection = CollectionPage(collected_page)
    row = collection.repository_row("niranjankagri/cypress-typescript-framework")
    expect(row).to_contain_text("fresh")
    expect(row).to_contain_text("1 cancelled, 1 success")
    expect(collection.view).to_contain_text("artifact report-ui-firefox not found")


@pytest.mark.usefixtures("chromium_only")
def test_test_investigation_shows_context_pattern_requirements_and_copies(page: Page) -> None:
    """Latest result, a pattern of 13 executions with one failure, duration chart and copy actions."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    test = TestsPage(page).open().open_test("adminEditsACustomer")

    expect(test.meta).to_contain_text("Latest result")
    expect(test.pattern).to_have_count(13)
    expect(test.meta).to_contain_text("12 passed, 1 failed or errored of 13")
    expect(test.charts).to_contain_text("Duration per execution")
    test.copy("Copy test identifier")
    expect(test.copied).to_be_visible()
    assert "adminEditsACustomer" in test.clipboard_text()


def test_compare_page_shows_two_builds_and_their_changes(page: Page) -> None:
    """Default: the last two builds; choosing TestNG's first two shows 10 slower tests with links."""
    compare = ComparePage(page).open("#/compare?framework=testng&base=f5a40d5&head=1d03232")
    expect(compare.heading("Compare builds", exact=False)).to_be_visible()
    expect(compare.baseline).to_have_value("f5a40d5")
    expect(compare.change_types).to_contain_text("slower (10)")
    expect(compare.rows).to_have_count(10)

    compare.comparison_build.select_option("e30ab76")
    expect(page).to_have_url(re.compile(r"head=e30ab76"))
    expect(compare.change_types).to_contain_text("slower (")
    compare.open_first_test()
    expect(page).to_have_url(re.compile(r"#/test\?"))


def test_filter_chips_quick_dates_job_filter_and_table_tools(page: Page) -> None:
    """Active filters as removable chips; a quick range sets From; tables sort and export CSV."""
    runs = RunsPage(page).open("#/runs?framework=testng")
    expect(runs.active_filter_chips).to_contain_text("Framework: testng")

    runs.quick_range("30 days")
    expect(page).to_have_url(re.compile(r"since=\d{4}-\d{2}-\d{2}"))
    expect(runs.active_filter_chips).to_contain_text("From:")
    runs.quick_range("All dates")
    runs.remove_filter("Framework: testng")
    expect(page).not_to_have_url(re.compile(r"framework="))

    runs.open()
    runs.sort_by("passed")  # ascending
    expect(runs.ascending_headers).to_have_count(1)
    first = runs.cell(runs.rows.first, 6).inner_text()
    runs.sort_by("passed")
    assert int(runs.cell(runs.rows.first, 6).inner_text()) >= int(first)
    runs.filter_rows("robot")
    expect(runs.rows).to_have_count(11)
    text = runs.download_csv()
    assert text.splitlines()[0].startswith("Run,Pipeline / job,Framework")
    assert len(text.strip().splitlines()) == 12  # header + the 11 filtered rows
    expect(runs.filter_select("job")).to_be_attached()


def test_a_trend_bar_opens_the_runs_of_its_day_with_the_keyboard(page: Page) -> None:
    """Each day's bar is a link with its numbers as name; Enter on it lists that day's runs."""
    trends = TrendsPage(page).open()
    bar = trends.day_bar("10-13")
    expect(bar).to_have_count(1)
    bar.focus()
    page.keyboard.press("Enter")

    expect(page).to_have_url(re.compile(r"#/runs\?.*since=2026-10-13.*until=2026-10-13"))
    expect(trends.heading("Runs")).to_be_visible()


@pytest.mark.parametrize("width", [390, 768, 1280])
@pytest.mark.parametrize(
    "route",
    [
        "#/coverage",
        "#/requirements",
        "#/tests",
        "#/runs",
        "#/stability",
        "#/trends",
        "#/compare",
        "#/pipelines",
        "#/attention",
        "#/search?q=checkout",
    ],
)
def test_no_horizontal_overflow_at_phone_tablet_and_desktop_widths(
    page: Page, route: str, width: int
) -> None:
    """The page itself never scrolls sideways; wide tables scroll inside their own box."""
    page.set_viewport_size({"width": width, "height": 900})
    dashboard = ClassicPage(page).open(route)
    expect(dashboard.view_heading).to_be_visible()

    assert dashboard.fits_the_window()


def test_theme_and_density_are_remembered(page: Page) -> None:
    """Dark chosen in the page wins over the system setting after a reload; Compact too."""
    overview = OverviewPage(page).open()
    overview.theme_select.select_option("dark")
    overview.compact_checkbox.check()
    page.reload()

    expect(overview.document_root).to_have_attribute("data-theme", "dark")
    expect(overview.body).to_have_class(re.compile("compact"))
    # The portfolio palette's dark background (--bg: #111918 in style.css)
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(17, 25, 24)"


def test_moving_to_another_page_puts_the_focus_on_its_heading(page: Page) -> None:
    """Keyboard and screen-reader users land on the new page, not on the old link."""
    overview = OverviewPage(page).open()
    expect(overview.heading("Overview")).to_be_visible()
    overview.go_to("Runs")

    expect(overview.heading("Runs")).to_be_focused()


def test_the_owner_filter_narrows_requirements_and_the_matrix_groups_by_owner(page: Page) -> None:
    """Owner = Admin team: 12 requirements, a chip, the address; the matrix has a By owner table."""
    requirements = RequirementsPage(page).open()
    expect(requirements.heading("By owner", exact=False)).to_be_visible()
    requirements.filter_select("owner").select_option("Admin team")

    expect(page).to_have_url(re.compile(r"owner=Admin\+team|owner=Admin%20team"))
    expect(requirements.requirement_rows).to_have_count(12)
    expect(requirements.active_filters).to_contain_text("Owner: Admin team")


def test_navigation_groups_and_the_collapsible_filter_area(page: Page) -> None:
    """Navigation follows product areas; URL filters stay active while the advanced filters collapse."""
    overview = OverviewPage(page).open("#/coverage?criticality=critical")

    for group in ("Investigate", "Coverage", "Execution", "Analytics", "Operations"):
        expect(overview.section_nav).to_contain_text(group)
    expect(overview.section_link("overview")).to_have_attribute("aria-current", "page")

    overview.filter_panel_toggle.click()
    expect(overview.filters).to_be_hidden()
    overview.filter_panel_toggle.click()
    expect(overview.filter_select("criticality")).to_have_value("critical")
    overview.go_to("Requirements")
    expect(page).to_have_url(re.compile(r"criticality=critical"))


def test_mobile_sections_menu_can_collapse_and_reopen(page: Page) -> None:
    """On a phone, the whole grouped navigation can be hidden and reopened."""
    page.set_viewport_size({"width": 390, "height": 844})
    overview = OverviewPage(page).open()

    sections = overview.mobile_sections_toggle
    attention = overview.nav_link("Needs attention")
    expect(sections).to_be_visible()
    expect(attention).to_be_hidden()
    sections.click()
    expect(attention).to_be_visible()
    sections.click()
    expect(attention).to_be_hidden()
    sections.click()
    attention.click()
    expect(overview.heading("Needs attention")).to_be_visible()


def test_critical_gap_preset_groups_findings_and_returns_to_filtered_results(page: Page) -> None:
    """The critical gap shortcut uses the existing attention API and keeps a back link from detail."""
    OverviewPage(page).open().preset("Critical gaps")

    expect(page).to_have_url(
        re.compile(r"#/attention\?.*kind=critical\+gap|#/attention\?.*kind=critical%20gap")
    )
    attention = AttentionPage(page)
    expect(attention.heading("Needs attention")).to_be_visible()
    group = attention.group("Investigate now")
    expect(group.locator("tbody tr")).to_have_count(2)
    expect(group.locator("table thead")).to_contain_text("Observed reason")
    expect(group.locator("table thead")).to_contain_text("Repository")
    expect(group.get_by_role("button", name=re.compile("Copy link for"))).to_have_count(2)

    group.locator("tbody td").nth(2).get_by_role("link").click()
    expect(attention.heading(re.compile("^(SHOP|ADMIN)-"))).to_be_visible()
    attention.back_to_filtered_results.click()
    expect(page).to_have_url(re.compile(r"#/attention\?.*kind=critical"))


def test_quick_views_and_metric_definitions_are_shareable(page: Page) -> None:
    """Presets keep their route filters in the address and KPI help states the metric limits."""
    overview = OverviewPage(page).open()
    overview.preset("Recent failures")
    expect(page).to_have_url(re.compile(r"#/tests\?.*outcome=failed.*since=\d{4}-\d{2}-\d{2}"))
    expect(TestsPage(page).outcome_filter).to_have_value("failed")

    overview.open()
    expect(overview.open_card_help("Execution pass rate")).to_contain_text("Skips are excluded")
    overview.open_guide()
    expect(overview.guide_dialog).to_be_visible()
    overview.close_guide()


def test_repository_requirement_breakdown_uses_observed_results_and_drills_down(
    page: Page, pipelines_url: str
) -> None:
    """Repository rows are limited to observed linked results; each count opens its exact evidence."""
    page.goto(f"{pipelines_url}/classic/#/requirements")
    requirements = RequirementsPage(page)
    repo_row = requirements.repository_rows.first
    expect(repo_row).to_contain_text("niranjankagri/cypress-typescript-framework")
    expect(page.get_by_text("does not imply that repository is expected", exact=False)).to_be_visible()
    observed_count = int(repo_row.locator("td").nth(1).inner_text())
    repo_row.get_by_role("link").last.click()
    expect(page).to_have_url(re.compile(r"observed=true"))
    rows = requirements.requirement_rows
    expect(rows).to_have_count(observed_count)
    expect(rows.first).to_contain_text("observed")
    rows.first.locator("td").first.get_by_role("link").click()
    expect(requirements.heading(re.compile("^(TB|SHOP|ADMIN|NOTES)-"))).to_be_visible()
    requirements.back_to_filtered_results.click()
    expect(page).to_have_url(re.compile(r"#/requirements\?"))


def test_a_table_that_fits_on_one_page_shows_no_pager(page: Page) -> None:
    """Five snapshot runs: no "Rows 1-5 of 5" and no Previous/Next (the hidden attribute wins)."""
    overview = OverviewPage(page).open()
    expect(overview.heading("Overview")).to_be_visible()

    expect(overview.pagers.first).to_be_hidden()
    assert all(not box.is_visible() for box in overview.pagers.all())


def test_every_page_says_the_requirements_are_synthetic(page: Page) -> None:
    """The sample catalog's notice is visible above every page, not only on the overview."""
    dashboard = ClassicPage(page)
    for route in ("#/coverage", "#/requirements", "#/pipelines"):
        dashboard.open(route)
        expect(dashboard.view_heading).to_be_visible()
        expect(dashboard.catalog_notice).to_contain_text("synthetic sample catalog")


def test_collection_problems_lead_to_their_pipeline_and_github_run(collected_page: Page) -> None:
    """Each problem links its pipeline and its run attempt on GitHub; so does the freshness line."""
    page = collected_page
    collection = CollectionPage(page).open()
    problem = collection.problem("report-ui-firefox not found")

    expect(problem.get_by_role("link", name="Open the run on GitHub")).to_have_attribute(
        "href",
        "https://github.com/niranjankagri/cypress-typescript-framework/actions/runs/38842296207/attempts/1",
    )
    problem.get_by_role("link", name=re.compile("pipeline 38842296207 attempt 1")).click()
    expect(page).to_have_url(re.compile(r"#/pipelines\?.*status=incomplete"))

    overview = OverviewPage(page).open()
    overview.data_fresh.get_by_role("link", name=re.compile("incomplete collection")).click()
    expect(page).to_have_url(re.compile(r"#/pipelines\?status=incomplete"))
    expect(overview.view_heading).to_have_text("Pipelines")


def test_operations_separates_snapshot_refresh_from_collection_freshness(collected_page: Page) -> None:
    """Operations shows the last good dashboard snapshot and last complete collection separately."""
    collection = CollectionPage(collected_page).open()

    expect(collection.heading("Dashboard snapshot", exact=False)).to_be_visible()
    expect(collected_page.get_by_text("It does not start a CI collection workflow.")).to_be_visible()
    expect(collected_page.get_by_role("columnheader", name="Last complete collection")).to_be_visible()
    repository = collection.rows.first
    expect(repository.locator("td").nth(3)).to_contain_text(re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2} UTC"))


def test_a_compare_link_to_an_unknown_build_still_offers_the_build_choice(page: Page) -> None:
    """A mistyped or pruned build in the address: an explanation and the selectors, not an error page."""
    compare = ComparePage(page).open("#/compare?base=f5a40d5&head=0000000")

    expect(compare.view_notes).to_contain_text("No runs of build 0000000 in this scope")
    expect(compare.baseline).to_be_visible()
    expect(compare.view_alerts).to_have_count(0)
    compare.comparison_build.select_option("1d03232")
    expect(page).to_have_url(re.compile(r"head=1d03232"))
    expect(compare.tables).to_be_visible()
