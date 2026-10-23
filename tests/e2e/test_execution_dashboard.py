"""Historical execution dashboard interactions against the checked-in result samples."""

from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import Page, Route, expect

pytestmark = pytest.mark.e2e


def test_execution_dashboard_suite_scope_and_history_link(page: Page) -> None:
    """Suite and ranking choices survive refresh; a ranking links to scoped test history and back."""
    page.goto("/#/executions")
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
    page.goto("/#/executions?repository=unknown/missing")
    expect(page.get_by_role("status").filter(has_text="No recorded executions")).to_be_visible()
    expect(page.locator(".execution-cards")).to_contain_text("Not recorded")


def test_mobile_rankings_keep_names_readable(page: Page) -> None:
    """Ranking tables scroll internally instead of squeezing test names into word-wide columns."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/#/executions")
    expect(page.locator("#view h1")).to_have_text("Test execution dashboard")
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
    page.goto("/#/executions")
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
    page.unroute(pattern)
    for request in held:
        request.continue_()
    expect(page.get_by_role("heading", name="Top 25 longest-running tests")).to_be_visible()
    page.reload()
    expect(page.locator("#execution-suite")).to_have_value(suite)
    expect(page.locator("#execution-limit")).to_have_value("25")
