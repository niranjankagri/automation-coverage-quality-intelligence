"""WCAG 2.2 A/AA checks with axe-core on every page, in light and dark themes (docs/dashboard.md).

axe-core finds a defined set of problems automatically (contrast, names, roles, structure); it
does not replace a review with a screen reader. Every rule it reports here must be fixed, not
excluded.
"""

import pytest
from axe_playwright_python.sync_playwright import Axe
from pages.classic import ClassicPage, OverviewPage, PipelinesPage, StabilityPage
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
    dashboard = OverviewPage(page).open()
    dashboard.set_theme(theme)
    dashboard.open(route)
    expect(dashboard.view_heading).to_be_visible()
    page.wait_for_load_state("networkidle")

    assert violations(page) == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_mobile_overview_has_no_wcag_violations(page: Page, theme: str) -> None:
    """The collapsed phone navigation and filters stay accessible in either theme."""
    page.set_viewport_size({"width": 390, "height": 844})
    overview = OverviewPage(page).open()
    overview.set_theme(theme)
    overview.open()
    expect(overview.view_heading).to_be_visible()
    expect(overview.mobile_sections_toggle).to_be_visible()

    assert violations(page) == []


def test_no_wcag_violations_with_pipelines_and_test_investigation(collected_page: Page) -> None:
    """The pages that need pipeline and collection data, and a test's investigation page."""
    page = collected_page
    dashboard = ClassicPage(page)
    for route in ("#/pipelines", "#/collection", "#/runs"):
        dashboard.open(route)
        expect(dashboard.view_heading).to_be_visible()
        page.wait_for_load_state("networkidle")
        assert violations(page) == [], route
    pipelines = PipelinesPage(page).open()
    pipelines.expand(pipelines.pipelines.first)
    assert violations(page) == []


def test_guide_dialog_has_no_wcag_violations(page: Page) -> None:
    """The keyboard-accessible first-use guide stays accessible when opened."""
    OverviewPage(page).open().open_guide()

    assert violations(page) == []


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_an_open_issue_draft_has_no_wcag_violations(recurring_page: Page, theme: str) -> None:
    """The draft's read-only text box, copy button and GitHub link stay accessible in either theme."""
    page = recurring_page
    OverviewPage(page).open().set_theme(theme)
    draft = StabilityPage(page).open().open_draft("#1 Recurring test failure")
    expect(draft.get_by_role("link", name="Review and submit on GitHub")).to_be_visible()
    page.wait_for_load_state("networkidle")

    assert violations(page) == []
