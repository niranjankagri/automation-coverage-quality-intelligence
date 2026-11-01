"""Historical execution dashboard interactions against the checked-in result samples."""

from urllib.parse import parse_qs, urlsplit

import pytest
from pages.classic import ExecutionsPage
from playwright.sync_api import Locator, Page, Route, expect

pytestmark = pytest.mark.e2e


def test_execution_dashboard_suite_scope_and_history_link(page: Page) -> None:
    """Suite and ranking choices survive refresh; a ranking links to scoped test history and back."""
    executions = ExecutionsPage(page).open()
    expect(executions.view_heading).to_have_text("Test execution dashboard")
    expect(executions.heading("Results by status", exact=False)).to_be_visible()
    expect(executions.heading("Top 10 longest-running tests", exact=False)).to_be_visible()
    options = executions.suite_options.all_text_contents()
    assert len(options) > 1
    suite = executions.suite_options.nth(1).get_attribute("value")
    assert suite
    executions.suite.select_option(suite)
    expect(executions.suite).to_have_value(suite)
    executions.limit.select_option("25")
    expect(executions.heading("Top 25 longest-running tests", exact=False)).to_be_visible()
    page.reload()
    expect(executions.suite).to_have_value(suite)
    expect(executions.limit).to_have_value("25")
    executions.first_ranked_test.click()
    expect(executions.view_heading).not_to_have_text("Test execution dashboard")
    executions.back_to_filtered_results.click()
    expect(executions.view_heading).to_have_text("Test execution dashboard")
    expect(executions.suite).to_have_value(suite)


def test_execution_dashboard_empty_scope(page: Page) -> None:
    """No results yields an explicit empty state rather than fabricated rates and timings."""
    executions = ExecutionsPage(page).open("#/executions?repository=unknown/missing")
    expect(page.get_by_role("status").filter(has_text="No recorded executions")).to_be_visible()
    expect(executions.cards).to_contain_text("Not recorded")


def test_mobile_rankings_keep_names_readable(page: Page) -> None:
    """Ranking tables scroll internally instead of squeezing test names into word-wide columns."""
    page.set_viewport_size({"width": 390, "height": 844})
    executions = ExecutionsPage(page).open()
    expect(executions.view_heading).to_have_text("Test execution dashboard")
    executions.open_first_ranking()
    region = executions.region(
        "Top 10 longest-running tests data; scroll horizontally on narrow screens", exact=False
    )
    expect(region).to_have_attribute("tabindex", "0")
    cell_box = region.locator("td").first.bounding_box()
    assert cell_box is not None
    assert cell_box["width"] >= 260
    assert executions.fits_the_window()


@pytest.mark.parametrize("first", ["suite", "limit"])
def test_quick_filter_changes_keep_current_url_state(page: Page, first: str) -> None:
    """An old visible select must not erase another filter while the replacement API call waits."""
    executions = ExecutionsPage(page).open()
    expect(executions.view_heading).to_have_text("Test execution dashboard")
    suite = executions.suite_options.nth(1).get_attribute("value")
    assert suite
    held: list[Route] = []
    pattern = "**/api/executions?**"
    page.route(pattern, lambda route: held.append(route))
    choices: list[tuple[Locator, str]] = [(executions.suite, suite), (executions.limit, "25")]
    if first == "limit":
        choices.reverse()
    for select, value in choices:
        with page.expect_request(lambda request: "/api/executions?" in request.url):
            select.select_option(value)
    # Both controls still belong to the original render: the slow requests have not completed.
    query = parse_qs(urlsplit(page.url).fragment.partition("?")[2])
    assert query["suite"] == [suite]
    assert query["limit"] == ["25"]
    for request in held:
        request.continue_()
    page.unroute(pattern)
    expect(executions.heading("Top 25 longest-running tests", exact=False)).to_be_visible()
    page.reload()
    expect(executions.suite).to_have_value(suite)
    expect(executions.limit).to_have_value("25")


def test_guided_repository_family_browser_and_back(collected_page: Page) -> None:
    """Real imported combinations drive the picker; changing parents clears child choices."""
    page = collected_page
    executions = ExecutionsPage(page).open()
    executions.choice("Choose a repository", "cypress typescript framework").click()
    executions.choice("Choose a test family", "UI").click()
    executions.choice("Choose a browser", "chrome").click()
    expect(executions.choice("Choose a browser", "chrome")).to_have_attribute("aria-pressed", "true")
    page.reload()
    expect(executions.choice("Choose a test family", "UI")).to_have_attribute("aria-pressed", "true")
    expect(executions.choice("Choose a browser", "chrome")).to_have_attribute("aria-pressed", "true")
    assert "kind=ui" in page.url
    assert "browser=chrome" in page.url
    executions.choice("Choose a test family", "API").click()
    expect(executions.region("Choose a job", exact=True)).to_be_visible()
    assert "browser=" not in page.url
    assert "kind=api" in page.url
    executions.choice("Choose a repository", "All repositories").click()
    expect(executions.choice("Choose a test family", "All tests")).to_have_attribute("aria-pressed", "true")
    assert "kind=" not in page.url
    page.go_back()
    expect(executions.choice("Choose a test family", "API")).to_have_attribute("aria-pressed", "true")


def test_chart_interaction_and_progressive_details(page: Page) -> None:
    """Charts are interactive without forcing tables open; detailed evidence stays available."""
    executions = ExecutionsPage(page).open()
    expect(executions.view_heading).to_be_visible()
    expect(executions.filters).to_be_hidden()
    expect(executions.rankings.first.locator("table")).to_be_hidden()
    failed = executions.status_buttons.get_by_role("button", name="failed")
    failed.click()
    expect(failed).to_have_attribute("aria-pressed", "true")
    expect(executions.donut_selection).to_contain_text("failed")
    executions.reset_chart()
    expect(failed).to_have_attribute("aria-pressed", "false")
    executions.advanced_filters_button.click()
    expect(executions.filters).to_be_visible()
    executions.advanced_filters_button.click()
    expect(executions.filters).to_be_hidden()
    executions.open_first_ranking()
    expect(executions.rankings.first.locator("table")).to_be_visible()
    expect(executions.back_to_portfolio).to_have_attribute("href", "https://niranjankagri.github.io/")


def test_daily_chart_preserves_guided_scope(collected_page: Page) -> None:
    """Selecting a day never broadens a repository/type/browser selection."""
    page = collected_page
    executions = ExecutionsPage(page).open(
        "#/executions?repository=niranjankagri%2Fcypress-typescript-framework&kind=ui&browser=chrome"
    )
    executions.open_first_day()
    expect(executions.view_heading).to_have_text("Test execution dashboard")
    query = parse_qs(urlsplit(page.url).fragment.partition("?")[2])
    assert query["kind"] == ["ui"]
    assert query["browser"] == ["chrome"]
    assert query["since"] == query["until"]


@pytest.mark.parametrize("path", ["/classic/", "/classic/#/"])
def test_classic_entry_keeps_the_original_visual_dashboard(page: Page, path: str) -> None:
    """Both classic landing URLs retain the original execution dashboard."""
    page.goto(path)  # the landing addresses themselves, without a screen route
    executions = ExecutionsPage(page)
    expect(executions.view_heading).to_have_text("Test execution dashboard")
    expect(executions.filters).to_be_hidden()
    executions.go_to("Coverage & release")
    expect(executions.view_heading).to_have_text("Overview")
    expect(executions.nav_link("Dashboard")).to_be_visible()
