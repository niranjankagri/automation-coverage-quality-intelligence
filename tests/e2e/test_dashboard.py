"""The dashboard in a real browser, against the sample data."""

import re

import pytest
from playwright.sync_api import Locator, Page, Route, expect

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
