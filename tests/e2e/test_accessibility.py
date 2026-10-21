"""WCAG 2.2 A/AA checks with axe-core on every page, in light and dark themes (docs/dashboard.md).

axe-core finds a defined set of problems automatically (contrast, names, roles, structure); it
does not replace a review with a screen reader. Every rule it reports here must be fixed, not
excluded.
"""

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

AXE = Axe()
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
PAGES = [
    "#/",
    "#/requirements",
    "#/requirement/SHOP-006",
    "#/tests",
    "#/runs",
    "#/stability",
    "#/trends",
    "#/compare?framework=testng&base=f5a40d5&head=1d03232",
    "#/pipelines",
    "#/collection",
    "#/search?q=checkout",
    "#/attention",
    "#/test?key=com.enterprise.automation.tests.ui.CustomerManagementTest%3A%3AadminEditsACustomer",
]


def violations(page: Page) -> list[str]:
    """axe-core's WCAG violations on the current page, one line each with an example element."""
    result = AXE.run(page, options={"runOnly": {"type": "tag", "values": TAGS}})
    return [
        f"{v['id']} ({v['impact']}): {v['help']} — e.g. {v['nodes'][0]['target']}"
        for v in result.response["violations"]
    ]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("route", PAGES)
def test_no_wcag_violations(page: Page, route: str, theme: str) -> None:
    """Every page, both themes: no violation of the WCAG 2.2 A/AA rules axe-core checks."""
    page.goto("/")
    page.evaluate(f"localStorage.setItem('qi-theme', '{theme}')")
    page.goto(f"/{route}")
    expect(page.locator("#view h1")).to_be_visible()
    page.wait_for_load_state("networkidle")

    assert violations(page) == []


def test_no_wcag_violations_with_pipelines_and_test_investigation(collected_page: Page) -> None:
    """The pages that need pipeline and collection data, and a test's investigation page."""
    page = collected_page
    for route in ("#/pipelines", "#/collection", "#/runs"):
        page.goto(f"/{route}")
        expect(page.locator("#view h1")).to_be_visible()
        page.wait_for_load_state("networkidle")
        assert violations(page) == [], route
    page.goto("/#/pipelines")
    page.locator("details.pipeline summary").first.click()
    assert violations(page) == []
