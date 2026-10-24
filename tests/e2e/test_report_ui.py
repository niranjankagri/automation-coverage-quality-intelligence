"""The report UI at / (docs/report-ui.md): filters, drill-downs, data rules, accessibility."""

import re

import pytest
from axe_playwright_python.sync_playwright import Axe
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.e2e

AXE = Axe()
TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"]
TB_Q = "repository=niranjankagri%2Fcypress-typescript-framework"
SECTIONS = {
    "overview": "Quality at a glance",
    "results": "Test Results",
    "failures": "Failures & Stability",
    "trends": "Trends",
    "coverage": "Coverage & Requirements",
}
SAMPLE_TEST = "com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer"


def violations(page: Page) -> list[str]:
    """axe-core's WCAG violations, one line each with an example element."""
    result = AXE.run(page, options={"runOnly": {"type": "tag", "values": TAGS}})
    return [f"{v['id']}: {v['help']} e.g. {v['nodes'][0]['target']}" for v in result.response["violations"]]


def heading(page: Page, text: str) -> None:
    """Wait until the section's own heading is shown (not the skeleton of another one)."""
    expect(page.locator("main h1")).to_have_text(text)
    expect(page.locator("main")).not_to_have_attribute("aria-busy", "true")


# ---- Overview: four different questions, and links to the evidence ----


def test_the_overview_keeps_pass_rate_coverage_gaps_and_readiness_apart(page: Page) -> None:
    """Samples: 100% pass rate, 86% of catalog test cases automated, 2 critical gaps, no gate."""
    page.goto("/")
    heading(page, "Quality at a glance")

    kpis = page.locator(".kpi")
    expect(kpis.nth(0)).to_contain_text("Execution pass rate100%")
    expect(kpis.nth(1)).to_contain_text("Automation coverage86%")
    expect(kpis.nth(2)).to_contain_text("Critical gaps2")
    expect(kpis.nth(3)).to_contain_text("Cannot evaluate")
    expect(page.locator(".big-number")).to_have_text("221")
    expect(page.locator(".compare tbody tr")).to_have_count(4)  # chrome, chromium, firefox, no browser


def test_main_dashboard_classic_and_preview_links_stay_available(page: Page) -> None:
    """Home is the new report, classic stays functional, and /next remains a working bookmark."""
    page.goto("/")
    heading(page, "Quality at a glance")
    expect(page.locator(".ring .seg-passed")).to_have_css("stroke", "rgb(21, 153, 104)")
    page.get_by_role("link", name="Classic dashboard", exact=True).click()
    expect(page).to_have_url(re.compile(r"/classic/"))
    expect(page.locator("#view h1")).to_be_visible()
    page.get_by_role("link", name="Quality Intelligence home", exact=False).click()
    heading(page, "Quality at a glance")
    page.goto("/next/#/results?status=passed")
    heading(page, "Test Results")


def test_browser_cards_open_scoped_results_and_keep_exact_numbers(page: Page) -> None:
    """Visual browser cards open their own results; the exact comparison remains available."""
    page.goto("/#/overview")
    heading(page, "Quality at a glance")
    card = page.locator("a.browser-card").filter(has_text="chromium").first
    expect(card).to_contain_text("results")
    page.get_by_text("Compare exact numbers", exact=True).click()
    expect(page.locator(".compare")).to_be_visible()
    card.click()
    heading(page, "Test Results")
    expect(page).to_have_url(re.compile(r"browser=chromium"))
    expect(page.get_by_role("button", name="Remove Browser chromium", exact=True)).to_be_visible()


def test_the_donut_and_the_trend_open_the_matching_results(page: Page) -> None:
    """A status in the donut opens those results; a day of the trend opens that day's results."""
    page.goto("/#/overview")
    heading(page, "Quality at a glance")
    page.locator(".legend a").filter(has_text="passed").click()

    heading(page, "Test Results")
    expect(page).to_have_url(re.compile(r"#/results\?status=passed$"))
    expect(page.get_by_role("button", name=re.compile(r"^passed"))).to_have_attribute("aria-pressed", "true")

    page.go_back()
    heading(page, "Quality at a glance")
    page.locator(".chart a").last.click()
    heading(page, "Test Results")
    expect(page).to_have_url(re.compile(r"since=2026-10-19&until=2026-10-19"))
    expect(page.get_by_role("button", name="Remove From 2026-10-19")).to_be_visible()


def test_a_headline_card_opens_its_evidence(page: Page) -> None:
    """Critical gaps opens Coverage at the gaps; readiness opens its explanation."""
    page.goto("/")
    heading(page, "Quality at a glance")
    page.locator(".kpi").filter(has_text="Critical gaps").click()

    heading(page, "Coverage & Requirements")
    expect(page.locator("#gaps")).to_be_in_viewport()
    page.go_back()
    heading(page, "Quality at a glance")
    page.locator(".kpi").filter(has_text="Release readiness").click()
    expect(page.locator("#readiness")).to_be_in_viewport()
    expect(page.locator("#readiness")).to_contain_text("no release gate is configured")


# ---- Filters: repository > test type > browser, parent resets, chips ----


def test_test_type_and_browser_follow_the_repository(collected_page: Page) -> None:
    """Only recorded choices; a new test type drops a browser it does not have; chips remove one."""
    page = collected_page
    page.goto(f"/#/results?{TB_Q}&kind=ui&browser=firefox")
    heading(page, "Test Results")
    expect(page.get_by_label("Browser", exact=True)).to_have_value("firefox")

    page.get_by_label("Test type", exact=True).select_option("api")
    heading(page, "Test Results")
    expect(page).not_to_have_url(re.compile("browser="))
    expect(page).to_have_url(re.compile("kind=api"))
    # API runs in one browser only (Electron): no browser choice to make
    expect(page.get_by_label("Browser", exact=True)).to_have_count(0)

    page.get_by_role("button", name=re.compile(r"^Remove Test type")).click()
    expect(page).not_to_have_url(re.compile("kind="))
    page.get_by_role("button", name="Reset all").click()
    expect(page).to_have_url(re.compile(r"#/results$"))


def test_an_unrecorded_combination_says_so(collected_page: Page) -> None:
    """A typed address with a combination no run has is called unsupported, with a reset."""
    page = collected_page
    page.goto(f"/#/overview?{TB_Q}&kind=performance")
    heading(page, "Quality at a glance")

    expect(page.get_by_text("No collected run has this combination of filters.")).to_be_visible()


# ---- Test details: the exact execution, its context and history ----


@pytest.mark.parametrize("engine", ["chrome", "firefox", "edge"])
def test_a_result_opens_the_execution_of_its_own_browser(collected_page: Page, engine: str) -> None:
    """The same test ran in three browsers: details show the one selected, with its own time."""
    page = collected_page
    page.goto(f"/#/results?{TB_Q}&kind=ui&browser={engine}&q=combines")
    heading(page, "Test Results")
    row = page.locator(".test-row").first
    time = row.locator(".test-time").inner_text()
    row.click()

    expect(page.locator(".test-title")).to_be_visible()
    expect(page).to_have_url(re.compile(rf"browser={engine}.*job=ui-{engine}.*run=[0-9a-f]{{64}}"))
    expect(page.locator(".facts").first).to_contain_text(f"ui-{engine} · {engine}")
    expect(page.locator(".execution-head strong")).to_have_text(time)


def test_back_and_shared_links_keep_the_selection(browser: Browser, collected_page: Page) -> None:
    """Back returns to the filtered list; the test's address opens the same execution elsewhere."""
    page = collected_page
    page.goto(f"/#/results?{TB_Q}&kind=ui&browser=edge&q=combines")
    heading(page, "Test Results")
    page.locator(".test-row").first.click()
    expect(page.locator(".test-title")).to_be_visible()
    shared = page.url
    ran_in = page.locator(".facts dd").first.inner_text()

    page.get_by_role("link", name="← Back to results").click()
    heading(page, "Test Results")
    expect(page.get_by_label("Search tests")).to_have_value("combines")
    page.go_back()
    expect(page.locator(".test-title")).to_be_visible()

    other = browser.new_page()
    other.goto(shared)
    expect(other.locator(".facts dd").first).to_have_text(ran_in)
    other.close()


def test_the_search_survives_a_reload(collected_page: Page) -> None:
    """Search and status filter are in the address (replaced while typing, not a new history entry)."""
    page = collected_page
    page.goto("/#/results")
    heading(page, "Test Results")
    page.get_by_label("Search tests").fill("filters")
    page.get_by_role("button", name=re.compile(r"^passed")).click()
    expect(page).to_have_url(re.compile(r"q=filters&status=passed"))

    page.reload()
    heading(page, "Test Results")
    expect(page.get_by_label("Search tests")).to_have_value("filters")
    expect(page.get_by_role("button", name=re.compile(r"^passed"))).to_have_attribute("aria-pressed", "true")


def test_details_tabs_separate_this_execution_history_and_browsers(collected_page: Page) -> None:
    """Keyboard tabs; history in this context apart from all contexts; three browsers compared."""
    page = collected_page
    page.goto(f"/#/results?{TB_Q}&kind=ui&browser=firefox&q=combines")
    heading(page, "Test Results")
    page.locator(".test-row").first.click()
    page.get_by_role("tab", name="Selected execution").focus()
    page.keyboard.press("ArrowRight")

    expect(page.get_by_role("tab", name="History")).to_have_attribute("aria-selected", "true")
    expect(page.get_by_role("tabpanel")).to_contain_text("In this context:")
    expect(page.get_by_role("tabpanel")).to_contain_text("Across all contexts")
    page.get_by_role("tab", name="Browser comparison").click()
    expect(page.get_by_role("tabpanel").locator("tbody tr")).to_have_count(3)
    page.get_by_role("tab", name="Evidence").click()
    expect(page.get_by_role("tabpanel")).to_contain_text("Not collected")


def test_long_lists_load_more_and_say_how_many(collected_page: Page) -> None:
    """No silent truncation: 'Showing 50 of 147', then 100 after Load more."""
    page = collected_page
    page.goto("/#/results?status=passed")
    heading(page, "Test Results")

    expect(page.locator(".list-status")).to_have_text("Showing 50 of 147 matching results")
    page.get_by_role("button", name="Load more").click()
    expect(page.locator(".list-status")).to_have_text("Showing 100 of 147 matching results")
    expect(page.locator(".flat-list .test-row")).to_have_count(100)


def test_the_newest_navigation_wins(collected_page: Page) -> None:
    """Quick section changes: the last one is shown, never an older response."""
    page = collected_page
    page.goto("/#/results")
    heading(page, "Test Results")
    page.evaluate("location.hash = '#/trends'; location.hash = '#/failures'; location.hash = '#/coverage'")

    heading(page, "Coverage & Requirements")
    page.wait_for_load_state("networkidle")
    expect(page.locator("main h1")).to_have_text("Coverage & Requirements")
    expect(page.get_by_role("link", name="Coverage & Requirements")).to_have_attribute("aria-current", "page")


def test_earlier_section_names_still_open(page: Page) -> None:
    """Links to the first report version (#/suites, #/categories ...) open the renamed sections."""
    page.goto("/#/suites")
    heading(page, "Test Results")
    expect(page).to_have_url(re.compile(r"#/results$"))


# ---- Coverage: requirements inside the report ----


def test_a_feature_opens_requirements_and_their_executions_in_scope(page: Page) -> None:
    """Overview feature bar > product opened > requirement page > the exact execution."""
    page.goto("/")
    heading(page, "Quality at a glance")
    page.locator(".feature-name").filter(has_text="Toolshop").click()

    heading(page, "Coverage & Requirements")
    page.get_by_role("link", name="SHOP-006").click()
    expect(page.locator("main h1")).to_contain_text("SHOP-006")
    page.locator(".test-case tbody a").first.click()
    expect(page.locator(".test-title")).to_be_visible()
    expect(page).to_have_url(re.compile(r"#/test\?.*key=.*run="))


# ---- Data rules on edge cases (skipped-only, failed, recovered, stale, unmapped, untimed) ----


def test_skipped_only_results_are_not_a_pass_rate(edge_page: Page) -> None:
    """The API job only skipped: 'No results' to rate, never 100%."""
    page = edge_page
    page.goto("/#/overview?kind=api")
    heading(page, "Quality at a glance")

    expect(page.locator(".kpi").first).to_contain_text("No results")
    expect(page.locator(".kpi").first).not_to_contain_text("100%")


def test_failures_are_not_product_defects_and_recovered_is_not_unstable(edge_page: Page) -> None:
    """One failed check; one new failure is unstable; the recovered test is listed apart."""
    page = edge_page
    page.goto("/#/failures")
    heading(page, "Failures & Stability")

    expect(page.locator(".stat").nth(1)).to_contain_text("1unstable tests")
    expect(page.locator(".stat").nth(2)).to_contain_text("1recovered")
    expect(page.get_by_text("failed check", exact=True)).to_be_visible()
    expect(page.locator("main")).not_to_contain_text("product defect")
    expect(page.locator("section[aria-labelledby='f-recovered']")).to_contain_text("recovers")


def test_stale_and_incomplete_collections_are_said_plainly(edge_page: Page) -> None:
    """The latest collection is 3 days old and one pipeline was incomplete."""
    page = edge_page
    page.goto("/")
    heading(page, "Quality at a glance")

    expect(page.locator(".notice-warning summary")).to_contain_text("Collection stale")
    expect(page.locator(".notice-warning")).to_contain_text("Collection incomplete")
    expect(page.locator(".freshness")).to_contain_text("1 incomplete collection(s) in 7 days")


def test_unmapped_coverage_and_missing_durations_are_named(edge_page: Page) -> None:
    """Results without requirements: 'Coverage not mapped'; a result without time: 'not recorded'."""
    page = edge_page
    page.goto("/#/coverage?repository=e%2Fedge")
    heading(page, "Coverage & Requirements")
    expect(page.locator("[data-empty='not-mapped']")).to_be_visible()

    page.goto("/#/results?q=works")
    heading(page, "Test Results")
    expect(page.locator(".test-time").first).to_have_text("not recorded")


# ---- Theme, keyboard, motion, accessibility, phone ----


def test_the_theme_button_works_like_the_portfolio(page: Page) -> None:
    """One button switches light/dark, remembered as na-theme, with the report's dark background."""
    page.emulate_media(color_scheme="light")
    page.goto("/")
    page.get_by_role("button", name="Use dark theme").click()
    page.reload()

    expect(page.locator("html")).to_have_attribute("data-theme", "dark")
    expect(page.get_by_role("button", name="Use light theme")).to_be_visible()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(17, 27, 43)"


def test_keyboard_focus_is_visible_and_motion_can_be_reduced(page: Page) -> None:
    """A focused link shows an outline; with reduced motion the loading shimmer does not move."""
    page.emulate_media(reduced_motion="reduce")
    page.goto("/")
    heading(page, "Quality at a glance")
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")

    assert page.evaluate("getComputedStyle(document.activeElement).outlineStyle") != "none"
    assert (
        page.evaluate(
            "(() => { const el = document.createElement('div'); el.className = 'skeleton';"
            " document.body.append(el); const name = getComputedStyle(el).animationName;"
            " el.remove(); return name; })()"
        )
        == "none"
    )


PAGES = [
    *SECTIONS.items(),
    (f"test?key={SAMPLE_TEST}", None),
    ("requirement?id=SHOP-006", None),
]


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize(("route", "title"), PAGES, ids=[route.split("?")[0] for route, _ in PAGES])
def test_no_wcag_violations_in_the_report(page: Page, route: str, title: str | None, theme: str) -> None:
    """Every section, a test and a requirement, in both themes."""
    page.goto("/")
    page.evaluate(f"localStorage.setItem('na-theme', '{theme}')")
    page.goto(f"/#/{route}")
    page.reload()
    if title:
        heading(page, title)
    else:
        expect(page.locator("main h1")).to_be_visible()
        expect(page.locator("main")).not_to_have_attribute("aria-busy", "true")
    page.wait_for_load_state("networkidle")

    assert violations(page) == []


@pytest.mark.parametrize(("route", "title"), SECTIONS.items(), ids=list(SECTIONS))
def test_every_section_fits_a_phone(page: Page, route: str, title: str) -> None:
    """390 px: the sidebar becomes a tab row, filters stack, nothing scrolls sideways."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(f"/#/{route}")
    heading(page, title)
    page.wait_for_load_state("networkidle")

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    assert violations(page) == []


def test_filters_fold_behind_a_toggle_on_a_phone(page: Page) -> None:
    """390 px: the filter bar is one button (with the number of active filters) until opened."""
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto("/#/results?kind=ui")
    heading(page, "Test Results")
    toggle = page.get_by_role("button", name="Filters (1 active)")

    expect(page.get_by_label("Repository", exact=True)).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(page.get_by_label("Repository", exact=True)).to_be_visible()
