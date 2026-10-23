"""The new report UI at /next/ (docs/report-ui.md): shell, Overview, switcher, theme, accessibility."""

import re

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

AXE = Axe()
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
TASKBOARD = "niranjankagri/cypress-typescript-framework"


def violations(page: Page) -> list[str]:
    """axe-core's WCAG violations, one line each with an example element."""
    result = AXE.run(page, options={"runOnly": {"type": "tag", "values": TAGS}})
    return [f"{v['id']}: {v['help']} e.g. {v['nodes'][0]['target']}" for v in result.response["violations"]]


def test_the_overview_shows_the_latest_snapshot_of_the_samples(page: Page) -> None:
    """Same numbers as the coverage page: 221 results, 100% pass rate, four suites, no failures."""
    page.goto("/next/")

    expect(page.get_by_role("heading", name="Overview", level=1)).to_be_visible()
    expect(page.locator(".big-number")).to_have_text("221")
    expect(page.get_by_role("img", name=re.compile(r"^Pass rate 100%"))).to_be_visible()
    expect(page.locator(".suite-row")).to_have_count(4)
    expect(page.get_by_text("No failures in the latest results.")).to_be_visible()
    expect(page.get_by_role("link", name="Overview")).to_have_attribute("aria-current", "page")


def test_the_repository_switcher_narrows_the_report_and_keeps_it_in_the_address(collected_page: Page) -> None:
    """Choosing the TaskBoard repository shows only its runs; the address can be shared or reloaded."""
    page = collected_page
    page.goto("/next/")
    page.get_by_label("Repository").select_option(TASKBOARD)

    expect(page).to_have_url(
        re.compile(r"#/overview\?repository=niranjankagri%2Fcypress-typescript-framework$")
    )
    expect(page.locator(".eyebrow")).to_have_text("Report · cypress-typescript-framework")
    page.reload()
    expect(page.get_by_label("Repository")).to_have_value(TASKBOARD)
    expect(page.locator(".suite-row")).to_have_count(1)
    page.get_by_role("link", name="Suites").click()
    expect(page).to_have_url(re.compile(r"#/suites\?repository="))


def test_a_section_still_to_build_links_its_classic_page(page: Page) -> None:
    """Suites is not built yet: it says so and opens the classic Tests page, not a dead end."""
    page.goto("/next/#/suites")

    expect(page.get_by_role("heading", name="Suites", level=1)).to_be_visible()
    expect(page.get_by_role("link", name="Open it in the classic dashboard")).to_have_attribute(
        "href", "/#/tests"
    )


def test_the_theme_button_works_like_the_portfolio(page: Page) -> None:
    """One button switches light/dark, remembered as na-theme, with the portfolio's dark background."""
    page.emulate_media(color_scheme="light")
    page.goto("/next/")
    page.get_by_role("button", name="Use dark theme").click()
    page.reload()

    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("button", name="Use light theme")).to_be_visible()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(17, 25, 24)"


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("route", ["#/overview", "#/categories"])
def test_no_wcag_violations_in_the_report(page: Page, route: str, theme: str) -> None:
    """The shell, the Overview and a section to come, in both themes."""
    page.goto("/next/")
    page.evaluate(f"localStorage.setItem('na-theme', '{theme}')")
    page.goto(f"/next/{route}")
    page.reload()
    expect(page.locator("main h1")).to_be_visible()
    page.wait_for_load_state("networkidle")

    assert violations(page) == []


def test_the_report_fits_a_phone(page: Page) -> None:
    """390 px: sections become a tab row, nothing scrolls sideways, still accessible."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/next/")
    expect(page.locator(".big-number")).to_have_text("221")
    page.wait_for_load_state("networkidle")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert violations(page) == []
