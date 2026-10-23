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
    "#/coverage",
    "#/requirements",
    "#/requirement/SHOP-006",
    "#/tests",
    "#/runs",
    "#/executions",
    "#/stability",
    "#/trends",
    "#/compare?framework=testng&base=f5a40d5&head=1d03232",
    "#/pipelines",
    "#/collection",
    "#/search?q=checkout",
    "#/attention",
    "#/attention?kind=critical%20gap",
    "#/requirements?stale=true",
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
    page.goto("/#/coverage")
    page.evaluate(f"localStorage.setItem('qi-theme', '{theme}')")
    page.goto(f"/{route}")
    expect(page.locator("#view h1")).to_be_visible()
    page.wait_for_load_state("networkidle")

    assert violations(page) == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_overview_has_no_wcag_violations(page: Page, theme: str) -> None:
    """The collapsed phone navigation and filters stay accessible in either theme."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/#/coverage")
    page.evaluate(f"localStorage.setItem('qi-theme', '{theme}')")
    page.goto("/#/coverage")
    expect(page.locator("#view h1")).to_be_visible()
    expect(page.locator(".mobile-nav > summary")).to_be_visible()

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


def test_guide_dialog_has_no_wcag_violations(page: Page) -> None:
    """The keyboard-accessible first-use guide stays accessible when opened."""
    page.goto("/#/coverage")
    page.get_by_role("button", name="Guide and glossary").click()

    assert violations(page) == []
