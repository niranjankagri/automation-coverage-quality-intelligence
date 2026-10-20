"""The dashboard in a real browser, against the sample data."""

import re
from pathlib import Path

import pytest
from playwright.sync_api import Browser, Locator, Page, Route, expect

from qualityintel.history.store import HistoryStore
from qualityintel.ingest.batch import import_pipeline
from qualityintel.live import Sources

SAMPLES = Path(__file__).parents[2] / "samples"

pytestmark = pytest.mark.e2e


def card(page: Page, label: str) -> Locator:
    """The overview card whose label is exactly ``label``."""
    return page.locator(".card").filter(
        has=page.locator(".label", has_text=re.compile(f"^{re.escape(label)}$"))
    )


def test_overview_shows_coverage_and_pass_rate_separately(page: Page) -> None:
    """Coverage numbers and the execution pass rate are different cards with their counts."""
    page.goto("/")

    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    expect(card(page, "Requirement coverage")).to_contain_text("90.5 %")
    expect(card(page, "Requirement coverage")).to_contain_text("38 of 42")
    expect(card(page, "Automation coverage")).to_contain_text("37 of 43")
    expect(card(page, "Execution pass rate")).to_contain_text("221 of 221")
    expect(page.get_by_role("link", name="SHOP-008")).to_be_visible()
    expect(page.get_by_role("link", name="ADMIN-012")).to_be_visible()


def test_metric_card_drills_down_to_the_requirements_behind_it(page: Page) -> None:
    """Requirement coverage card -> the four requirements without tests."""
    page.goto("/")

    card(page, "Requirement coverage").click()

    expect(page.get_by_role("heading", name="Requirements", exact=True)).to_be_visible()
    expect(page.locator("tbody tr")).to_have_count(4)
    expect(page.get_by_label("Status")).to_have_value("no tests")


def test_filter_changes_every_number_and_stays_in_the_url(page: Page) -> None:
    """Criticality critical: 13 requirements; the filter is part of the address."""
    page.goto("/")

    page.get_by_label("Criticality").select_option("critical")

    expect(card(page, "Requirements in scope")).to_contain_text("13")
    expect(page).to_have_url(re.compile(r"criticality=critical"))
    page.get_by_role("link", name="Requirements", exact=True).click()
    expect(page.locator("tbody tr")).to_have_count(13)
    page.get_by_role("button", name="Clear").click()
    expect(page.locator("tbody tr")).to_have_count(42)


def test_requirement_detail_shows_cases_and_latest_executions(page: Page) -> None:
    """SHOP-006 -> its automated checkout case with four Playwright executions."""
    page.goto("/#/requirement/SHOP-006")

    expect(page.get_by_role("heading", name=re.compile("^SHOP-006"))).to_be_visible()
    expect(page.get_by_text("guests are asked to sign in at checkout.")).to_be_visible()  # description
    expect(page.get_by_text("TC-SHOP-CHECKOUT")).to_be_visible()
    expect(page.locator("tbody tr")).to_have_count(4)


def test_test_history_shows_the_real_selenium_failure(page: Page) -> None:
    """The 13 Oct Firefox timeout is in the history and its message can be expanded."""
    page.goto("/#/tests")
    page.get_by_label("Search").fill("adminEditsACustomer")
    page.get_by_role("link", name=re.compile("adminEditsACustomer")).click()

    expect(page.locator("tbody tr")).to_have_count(13)
    failed_row = page.locator("tbody tr").filter(has=page.locator(".badge.failed"))
    expect(failed_row).to_have_count(1)
    failed_row.locator("summary").click()
    expect(failed_row.locator("pre.trace")).to_contain_text("TimeoutException")


def test_run_detail_lists_failures_first(page: Page) -> None:
    """The first Playwright attempt of 19 Oct: the failed checkout test is the first row."""
    page.goto("/#/runs?framework=playwright")
    page.get_by_role("link", name=re.compile("39229363499-attempt1")).click()

    first = page.locator("tbody tr").first
    expect(first.locator(".badge")).to_have_text("failed")
    expect(first).to_contain_text("customer can order two products")


def test_empty_scope_has_an_empty_state(page: Page) -> None:
    """A browser with no runs: no snapshot table, an explanation instead."""
    page.goto("/#/?browser=webkit")

    expect(page.get_by_text("No runs in this scope")).to_be_visible()
    expect(card(page, "Execution pass rate")).to_contain_text("n/a")


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
    page.goto("/")

    expect(page.get_by_role("alert")).to_contain_text("500: database offline")
    page.get_by_role("button", name="Retry").click()
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()


def test_unknown_page_and_unknown_requirement_show_errors(page: Page) -> None:
    """Bad links end in a readable message, not a blank page."""
    page.goto("/#/nowhere")
    expect(page.get_by_role("alert")).to_contain_text("This page does not exist.")

    page.goto("/#/requirement/NOPE-1")
    expect(page.get_by_role("alert")).to_contain_text("unknown requirement 'NOPE-1'")


@pytest.mark.parametrize("width", [390, 768])
def test_layout_fits_small_screens(page: Page, width: int) -> None:
    """Phone and tablet width: no sideways scrolling of the page; wide tables scroll inside."""
    page.set_viewport_size({"width": width, "height": 800})
    for path in ("/", "/#/requirements", "/#/tests", "/#/runs", "/#/stability", "/#/trends"):
        page.goto(path)
        expect(page.locator("#view h1")).to_be_visible()
        overflow = page.evaluate(
            "document.documentElement.scrollWidth - document.documentElement.clientWidth"
        )
        assert overflow <= 0, f"{path} scrolls sideways by {overflow}px at {width}px"


def test_keyboard_users_can_skip_to_the_content(page: Page) -> None:
    """First Tab reaches the skip link; it moves focus to the main region."""
    page.goto("/")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()

    page.keyboard.press("Tab")
    expect(page.get_by_role("link", name="Skip to content")).to_be_focused()
    page.keyboard.press("Enter")
    expect(page.locator("main")).to_be_focused()


def test_stability_page_shows_flaky_candidates_with_evidence(page: Page) -> None:
    """Four flaky candidates; each row says why; a smaller window forgets the 13 Oct failure."""
    page.goto("/#/stability")

    expect(page.get_by_role("heading", name="Stability", exact=True)).to_be_visible()
    expect(card(page, "Flaky candidate")).to_contain_text("4")
    edits_row = page.locator("tbody tr").filter(has_text="adminEditsACustomer")
    expect(edits_row).to_contain_text("passed and failed on the same build (f5a40d5)")
    expect(page.locator("ol.strip")).to_have_count(5)

    page.get_by_label("Window").select_option("5")

    expect(page).to_have_url(re.compile(r"window=5"))
    expect(page.locator("tbody tr").filter(has_text="adminEditsACustomer")).to_have_count(0)


def test_trends_page_draws_what_the_api_says(page: Page) -> None:
    """Every number in the 'Test results' table equals the API's daily counts; the jump in suites is explained."""
    page.goto("/#/trends")
    expect(page.get_by_role("heading", name="Trends", exact=True)).to_be_visible()
    daily = page.request.get("/api/trends").json()["daily"]

    results = page.locator("figure.chart").filter(has_text="Test results")
    results.get_by_text("Show the numbers").click()
    rows = results.locator("tbody tr")
    expect(rows).to_have_count(len(daily))
    for i, point in enumerate(daily):
        cells = rows.nth(i).locator("td")
        expect(cells.nth(0)).to_have_text(point["day"])
        expect(cells.nth(1)).to_have_text(str(point["counts"]["passed"]))
        expect(cells.nth(2)).to_have_text(str(point["counts"]["failed"]))
    expect(page.get_by_role("note")).to_contain_text(
        "the set of run contexts grows on 2026-10-09, 2026-10-13, 2026-10-17"
    )
    expect(page.locator("figure.chart")).to_have_count(4 + 5)  # four daily charts, one per run context


def test_date_filter_narrows_the_trend_and_stays_in_the_url(page: Page) -> None:
    """From 13 Oct to 15 Oct: three days, filter kept in the address."""
    page.goto("/#/trends")
    expect(page.get_by_role("heading", name="Trends", exact=True)).to_be_visible()

    page.get_by_label("From", exact=True).fill("2026-10-13")
    expect(page).to_have_url(re.compile(r"since=2026-10-13"))
    page.get_by_label("To", exact=True).fill("2026-10-15")

    expect(page).to_have_url(
        re.compile(r"since=2026-10-13.*until=2026-10-15|until=2026-10-15.*since=2026-10-13")
    )
    expect(page.locator("figure.chart").filter(has_text="Test results")).to_contain_text(
        "3 days from 2026-10-13 to 2026-10-15"
    )


def test_trends_without_runs_in_scope_say_so(page: Page) -> None:
    """A date range with no runs: no chart, an explanation."""
    page.goto("/#/trends?since=2030-01-01")

    expect(page.get_by_text("No dated runs in this scope")).to_be_visible()
    expect(page.locator("figure.chart")).to_have_count(0)


def test_a_late_response_for_an_older_address_is_not_shown(page: Page) -> None:
    """Two filter changes in a row; the first answer arrives last and must be ignored."""
    delayed: list[Route] = []

    def hold_first(route: Route) -> None:
        if "until=" in route.request.url or delayed:
            route.continue_()
        else:
            delayed.append(route)  # answered only after the newer request finished

    page.goto("/#/trends")
    expect(page.get_by_role("heading", name="Trends", exact=True)).to_be_visible()
    page.route("**/api/trends?*", hold_first)

    page.get_by_label("From", exact=True).fill("2026-10-13")
    page.get_by_label("To", exact=True).fill("2026-10-15")
    chart = page.locator("figure.chart").filter(has_text="Test results")
    expect(chart).to_contain_text("3 days from 2026-10-13 to 2026-10-15")
    assert delayed, "the first request was not held back"
    delayed[0].continue_()
    page.wait_for_load_state("networkidle")

    expect(chart).to_contain_text("3 days from 2026-10-13 to 2026-10-15")


def test_pipelines_page_shows_the_cancelled_run_as_incomplete(pipelines_page: Page) -> None:
    """Both real pipelines; naming the five jobs marks the cancelled one, and the URL keeps them."""
    page = pipelines_page
    page.goto("/#/pipelines")
    expect(page.get_by_role("heading", name="Pipelines", exact=True)).to_be_visible()
    complete = page.locator("details.pipeline").filter(has_text="Pipeline 39238241112")
    cancelled = page.locator("details.pipeline").filter(has_text="Pipeline 38842296207")
    expect(cancelled.locator("summary .badge")).to_have_text("complete")  # nothing says a job is missing yet
    expect(page.get_by_role("note")).to_contain_text("No expected jobs given")

    page.get_by_label("Expected jobs").fill("api, ui-chrome, ui-firefox, ui-edge, component")
    page.get_by_label("Expected jobs").press("Enter")

    expect(page).to_have_url(re.compile(r"jobs=api"))
    expect(cancelled.locator("summary .badge")).to_have_text("incomplete")
    cancelled.locator("summary").click()  # expand: jobs and problems
    expect(cancelled.locator("tr.missing")).to_contain_text("ui-firefox")
    expect(cancelled).to_contain_text("job ui-firefox reported no results")
    expect(complete.locator("summary .badge")).to_have_text("complete")
    expect(complete.locator("tbody tr")).to_have_count(5)
    expect(page.get_by_role("note")).to_have_count(0)
    expect(page.locator("#view")).not_to_contain_text("null")  # an empty slot must not print "null"


def test_status_chips_filter_the_pipelines_and_stay_in_the_address(pipelines_page: Page) -> None:
    """With the five jobs expected: 1 incomplete, 1 complete; a chip keeps only its pipelines."""
    page = pipelines_page
    page.goto("/#/pipelines?jobs=api,ui-chrome,ui-firefox,ui-edge,component")
    chips = page.get_by_role("navigation", name="Pipeline status")
    expect(chips).to_contain_text("All (2)")

    chips.get_by_role("link").filter(has_text="incomplete").click()

    expect(page).to_have_url(re.compile(r"status=incomplete"))
    expect(page.locator("details.pipeline")).to_have_count(1)
    expect(page.locator("details.pipeline")).to_contain_text("Pipeline 38842296207")


def test_runs_page_names_the_pipeline_job(pipelines_page: Page) -> None:
    """The run list has a pipeline / job column; a run's page repeats it."""
    page = pipelines_page
    page.goto("/#/runs")
    row = page.get_by_role("row").filter(has_text="ui-firefox/ui-firefox.json")
    expect(row).to_contain_text("39238241112 / ui-firefox")

    row.get_by_role("link").click()
    expect(page.locator("dl.meta")).to_contain_text("39238241112 / ui-firefox")


def test_with_a_login_the_whole_dashboard_works_after_signing_in(browser: Browser, secured_url: str) -> None:
    """The browser sends the login with the front end's own API calls too: the data appears."""
    anonymous = browser.new_context(base_url=secured_url)
    assert anonymous.new_page().goto("/").status == 401  # type: ignore[union-attr]
    anonymous.close()

    context = browser.new_context(
        base_url=secured_url, http_credentials={"username": "qi", "password": "correct horse battery"}
    )
    page = context.new_page()
    page.goto("/#/")
    expect(page.get_by_role("heading", name="Overview")).to_be_visible()
    expect(page.locator("#data-size")).to_contain_text("42 requirements")
    page.get_by_role("link", name="Trends", exact=True).click()
    expect(page.locator("figure.chart").first).to_be_visible()
    context.close()


def test_new_history_appears_without_a_restart_and_the_filters_stay(
    live_page: Page, live_server: tuple[str, Sources]
) -> None:
    """A run is stored while the page is open: Refresh shows it, the filtered address is kept."""
    page = live_page
    _, sources = live_server
    page.goto("/#/runs?framework=pytest")
    rows = page.locator("#view tbody tr")
    expect(rows).to_have_count(3)
    expect(page.locator("#data-fresh")).to_contain_text("Data loaded")

    assert sources.database is not None
    with HistoryStore(sources.database) as store:
        newer = import_pipeline({"api": [str(SAMPLES / "results" / "pytest-notes-api")]}, "p#2").runs[3:4]
        store.add_all(newer)
    page.get_by_role("button", name="Refresh").click()

    expect(rows).to_have_count(4)
    expect(page).to_have_url(re.compile(r"#/runs\?framework=pytest$"))
    expect(page.get_by_label("Framework")).to_have_value("pytest")
    expect(page.locator("#data-stale")).to_be_hidden()


def test_a_failed_refresh_keeps_the_data_and_warns(live_page: Page, live_server: tuple[str, Sources]) -> None:
    """The database becomes unreadable: the page keeps its figures and says they are stale."""
    page = live_page
    _, sources = live_server
    page.goto("/#/runs")
    rows = page.locator("#view tbody tr")
    expect(rows).to_have_count(3)

    assert sources.database is not None
    sources.database.write_bytes(b"not a database" * 100)
    page.get_by_role("button", name="Refresh").click()

    expect(page.locator("#data-stale")).to_be_visible()
    expect(page.locator("#data-stale")).to_contain_text("The last refresh failed")
    page.reload()
    expect(rows).to_have_count(3)  # still the last good data


def test_the_repository_selection_is_kept_across_pages_and_reloads(pipelines_page: Page) -> None:
    """Chosen once, in the address, applied on every page."""
    page = pipelines_page
    page.goto("/#/runs")
    page.get_by_label("Repository").select_option("niranjankagri/cypress-typescript-framework")

    expect(page).to_have_url(re.compile(r"repository=niranjankagri%2Fcypress-typescript-framework"))
    expect(page.locator("#view tbody tr")).to_have_count(9)
    page.get_by_role("link", name="Pipelines", exact=True).click()
    expect(page).to_have_url(re.compile(r"#/pipelines\?.*repository="))
    page.reload()
    expect(page.get_by_label("Repository")).to_have_value("niranjankagri/cypress-typescript-framework")


def test_overview_shows_the_release_status_with_its_reasons(page: Page) -> None:
    """Without a gate the status is Unknown, never Ready; the numbers are the API's."""
    page.goto("/#/")
    panel = page.get_by_role("region", name="Release status")
    expect(panel).to_contain_text("Unknown")
    expect(panel).to_contain_text("no release gate is configured")
    expect(card(page, "Test executions")).to_contain_text("221")
    expect(card(page, "Flaky candidates")).to_contain_text("4")


def test_explorer_links_to_github_and_the_collection_page_shows_health(collected_page: Page) -> None:
    """The cancelled run is incomplete with its missing artifact; links open the exact run; health is fresh."""
    page = collected_page
    page.goto("/#/pipelines")
    cancelled = page.locator("details.pipeline").filter(has_text="#6")
    expect(cancelled.locator("summary .badge")).to_have_text("incomplete")
    cancelled.locator("summary").click()
    expect(cancelled).to_contain_text("CI concluded: cancelled")
    expect(cancelled).to_contain_text("artifact report-ui-firefox not found")
    run_link = cancelled.get_by_role("link", name="Open the workflow run on GitHub")
    expect(run_link).to_have_attribute(
        "href", "https://github.com/niranjankagri/cypress-typescript-framework/actions/runs/38842296207"
    )
    expect(run_link).to_have_attribute("rel", "noopener noreferrer")

    page.get_by_role("link", name="Collection", exact=True).click()
    row = page.get_by_role("row").filter(has_text="niranjankagri/cypress-typescript-framework")
    expect(row).to_contain_text("fresh")
    expect(row).to_contain_text("1 cancelled, 1 success")
    expect(page.locator("#view")).to_contain_text("artifact report-ui-firefox not found")
