"""Historical execution dashboard interactions against the checked-in result samples."""

from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e


def test_execution_dashboard_suite_scope_and_history_link(page: Page) -> None:
    """Suite and ranking choices survive refresh; a ranking links to scoped test history and back."""
    page.goto("/classic/#/executions")
    expect(page.locator("#view h1")).to_have_text("Test execution dashboard")
    expect(page.get_by_role("heading", name="Results by status")).to_be_visible()
    expect(page.get_by_role("heading", name="Top 10 longest-running tests")).to_be_visible()
    options = page.locator("#execution-suite option").all_text_contents()
    assert len(options) > 1
    suite = page.locator("#execution-suite option").nth(1).get_attribute("value")
    assert suite
    page.locator("#execution-suite").select_option(suite)
    expect(page.locator("#execution-suite")).to_have_value(suite)
    page.locator("#execution-limit").select_option("25")
    expect(page.get_by_role("heading", name="Top 25 longest-running tests")).to_be_visible()
    page.reload()
    expect(page.locator("#execution-suite")).to_have_value(suite)
    expect(page.locator("#execution-limit")).to_have_value("25")
    target = page.locator(".execution-panel a.key").first
    target.click()
    expect(page.locator("#view h1")).not_to_have_text("Test execution dashboard")
    page.get_by_role("link", name="Back to filtered results").click()
    expect(page.locator("#view h1")).to_have_text("Test execution dashboard")
    expect(page.locator("#execution-suite")).to_have_value(suite)


def test_execution_dashboard_empty_scope(page: Page) -> None:
    """No results yields an explicit empty state rather than fabricated rates and timings."""
    page.goto("/classic/#/executions?repository=unknown/missing")
    expect(page.get_by_role("status").filter(has_text="No recorded executions")).to_be_visible()
    expect(page.locator(".execution-cards")).to_contain_text("Not recorded")


def test_mobile_rankings_keep_names_readable(page: Page) -> None:
    """Ranking tables scroll internally instead of squeezing test names into word-wide columns."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/classic/#/executions")
    expect(page.locator("#view h1")).to_have_text("Test execution dashboard")
    page.locator(".ranking-details > summary").first.click()
    region = page.get_by_role(
        "region", name="Top 10 longest-running tests data; scroll horizontally on narrow screens"
    )
    expect(region).to_have_attribute("tabindex", "0")
    cell_box = region.locator("td").first.bounding_box()
    assert cell_box is not None
    assert cell_box["width"] >= 260
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")


@pytest.mark.parametrize("first", ["suite", "limit"])
def test_quick_filter_changes_keep_current_url_state(page: Page, first: str) -> None:
    """An old visible select must not erase another filter while the replacement API call waits."""
    page.goto("/classic/#/executions")
    expect(page.locator("#view h1")).to_have_text("Test execution dashboard")
    suite = page.locator("#execution-suite option").nth(1).get_attribute("value")
    assert suite
    held: list[Route] = []
    pattern = "**/api/executions?**"
    page.route(pattern, lambda route: held.append(route))
    choices = [("#execution-suite", suite), ("#execution-limit", "25")]
    if first == "limit":
        choices.reverse()
    for selector, value in choices:
        with page.expect_request(lambda request: "/api/executions?" in request.url):
            page.locator(selector).select_option(value)
    # Both controls still belong to the original render: the slow requests have not completed.
    query = parse_qs(urlsplit(page.url).fragment.partition("?")[2])
    assert query["suite"] == [suite]
    assert query["limit"] == ["25"]
    for request in held:
        request.continue_()
    page.unroute(pattern)
    expect(page.get_by_role("heading", name="Top 25 longest-running tests")).to_be_visible()
    page.reload()
    expect(page.locator("#execution-suite")).to_have_value(suite)
    expect(page.locator("#execution-limit")).to_have_value("25")


def test_guided_repository_family_browser_and_back(collected_page: Page) -> None:
    """Real imported combinations drive the picker; changing parents clears child choices."""
    page = collected_page
    page.goto("/classic/#/executions")
    repos = page.get_by_role("region", name="Choose a repository", exact=True)
    repos.get_by_role("button", name="cypress typescript framework", exact=True).click()
    families = page.get_by_role("region", name="Choose a test family", exact=True)
    families.get_by_role("button", name="UI", exact=True).click()
    browsers = page.get_by_role("region", name="Choose a browser", exact=True)
    browsers.get_by_role("button", name="chrome", exact=True).click()
    expect(browsers.get_by_role("button", name="chrome", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    page.reload()
    expect(families.get_by_role("button", name="UI", exact=True)).to_have_attribute("aria-pressed", "true")
    expect(browsers.get_by_role("button", name="chrome", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    assert "kind=ui" in page.url
    assert "browser=chrome" in page.url
    families.get_by_role("button", name="API", exact=True).click()
    expect(page.get_by_role("region", name="Choose a job", exact=True)).to_be_visible()
    assert "browser=" not in page.url
    assert "kind=api" in page.url
    repos.get_by_role("button", name="All repositories", exact=True).click()
    expect(families.get_by_role("button", name="All tests", exact=True)).to_have_attribute(
        "aria-pressed", "true"
    )
    assert "kind=" not in page.url
    page.go_back()
    expect(families.get_by_role("button", name="API", exact=True)).to_have_attribute("aria-pressed", "true")


def test_chart_interaction_and_progressive_details(page: Page) -> None:
    """Charts are interactive without forcing tables open; detailed evidence stays available."""
    page.goto("/classic/#/executions")
    expect(page.locator("#view h1")).to_be_visible()
    expect(page.locator("#filters")).to_be_hidden()
    expect(page.locator(".ranking-details").first.locator("table")).to_be_hidden()
    failed = page.get_by_role("group", name="Explore result status").get_by_role("button", name="failed")
    failed.click()
    expect(failed).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".donut-selection")).to_contain_text("failed")
    page.get_by_role("button", name="Reset chart", exact=True).click()
    expect(failed).to_have_attribute("aria-pressed", "false")
    page.get_by_role("button", name="Advanced filters", exact=True).click()
    expect(page.locator("#filters")).to_be_visible()
    page.get_by_role("button", name="Advanced filters", exact=True).click()
    expect(page.locator("#filters")).to_be_hidden()
    page.locator(".ranking-details > summary").first.click()
    expect(page.locator(".ranking-details").first.locator("table")).to_be_visible()
    expect(page.get_by_role("link", name="← Back to portfolio")).to_have_attribute(
        "href", "https://niranjankagri.github.io/"
    )


def test_daily_chart_preserves_guided_scope(collected_page: Page) -> None:
    """Selecting a day never broadens a repository/type/browser selection."""
    page = collected_page
    page.goto(
        "/classic/#/executions?repository=niranjankagri%2Fcypress-typescript-framework&kind=ui&browser=chrome"
    )
    page.get_by_role("group", name="Bars, one link per day").get_by_role("link").first.click()
    expect(page.locator("#view h1")).to_have_text("Test execution dashboard")
    query = parse_qs(urlsplit(page.url).fragment.partition("?")[2])
    assert query["kind"] == ["ui"]
    assert query["browser"] == ["chrome"]
    assert query["since"] == query["until"]


@pytest.mark.parametrize("path", ["/classic/", "/classic/#/"])
def test_classic_entry_keeps_the_original_visual_dashboard(page: Page, path: str) -> None:
    """Both classic landing URLs retain the original execution dashboard."""
    page.goto(path)
    expect(page.locator("#view h1")).to_have_text("Test execution dashboard")
    expect(page.locator("#filters")).to_be_hidden()
    page.get_by_role("link", name="Coverage & release", exact=True).click()
    expect(page.locator("#view h1")).to_have_text("Overview")
    expect(page.get_by_role("link", name="Dashboard", exact=True)).to_be_visible()
