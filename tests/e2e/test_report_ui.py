"""The report UI at / (docs/report-ui.md): filters, drill-downs, data rules, accessibility."""

import re

import pytest
from axe_playwright_python.sync_playwright import Axe
from pages.classic import ClassicPage
from pages.report import ReportPage
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


# ---- Overview: four different questions, and links to the evidence ----


def test_the_overview_keeps_pass_rate_coverage_gaps_and_readiness_apart(page: Page) -> None:
    """Samples: 100% pass rate, 86% of catalog test cases automated, 2 critical gaps, no gate."""
    report = ReportPage(page).open()
    report.wait_for_section("Quality at a glance")

    expect(report.kpis.nth(0)).to_contain_text("Execution pass rate100%")
    expect(report.kpis.nth(1)).to_contain_text("Automation coverage86%")
    expect(report.kpis.nth(2)).to_contain_text("Critical gaps2")
    expect(report.kpis.nth(3)).to_contain_text("Cannot evaluate")
    expect(report.big_number).to_have_text("221")
    expect(report.browser_comparison_rows).to_have_count(4)  # chrome, chromium, firefox, no browser


def test_main_dashboard_classic_and_preview_links_stay_available(page: Page) -> None:
    """Home is the new report, classic stays functional, and /next remains a working bookmark."""
    report = ReportPage(page).open()
    report.wait_for_section("Quality at a glance")
    expect(report.link("Portfolio")).to_have_attribute("href", "https://niranjankagri.github.io/")
    # The name/logo leads to the report home; only the Portfolio link leaves the site
    expect(report.home_link).to_have_attribute("href", "/")
    expect(report.passed_ring_segment).to_have_css("stroke", "rgb(21, 153, 104)")
    report.link("Classic dashboard").click()
    expect(page).to_have_url(re.compile(r"/classic/"))
    classic = ClassicPage(page)
    expect(classic.view_heading).to_be_visible()
    report.home_link.click()
    report.wait_for_section("Quality at a glance")
    report.link("Classic dashboard").click()
    expect(classic.view_heading).to_be_visible()
    report.link("Quality Intelligence home", exact=False).click()
    report.wait_for_section("Quality at a glance")
    page.goto("/next/#/results?status=passed")
    report.wait_for_section("Test Results")


@pytest.mark.parametrize(("theme", "ink"), [("light", "rgb(23, 23, 23)"), ("dark", "rgb(241, 243, 247)")])
def test_scope_names_are_neutral_and_counts_keep_repository_navigation(
    pipelines_page: Page, theme: str, ink: str
) -> None:
    """Repository names remain readable and clickable; exact outcomes replace decorative bars."""
    report = ReportPage(pipelines_page).open()
    report.set_theme(theme)
    pipelines_page.reload()
    report.wait_for_section("Quality at a glance")
    link = report.scope_links.first
    expect(link).to_have_css("color", ink)
    expect(report.heading).to_have_css("color", ink)
    expect(report.scope.locator(".stack")).to_have_count(0)
    expect(report.scope.locator(".suite-outcomes").first).to_contain_text("passed")
    link.click()
    report.wait_for_section("Quality at a glance")
    expect(pipelines_page).to_have_url(re.compile(r"repository=niranjankagri%2Fcypress-typescript-framework"))


def test_browser_cards_open_scoped_results_and_keep_exact_numbers(page: Page) -> None:
    """Visual browser cards open their own results; the exact comparison remains available."""
    report = ReportPage(page).open("overview")
    report.wait_for_section("Quality at a glance")
    card = report.browser_card("chromium")
    expect(card).to_contain_text("results")
    report.show_exact_browser_numbers()
    expect(report.browser_comparison).to_be_visible()
    card.click()
    report.wait_for_section("Test Results")
    expect(page).to_have_url(re.compile(r"browser=chromium"))
    expect(report.remove_chip("Remove Browser chromium", exact=True)).to_be_visible()


def test_the_donut_and_the_trend_open_the_matching_results(page: Page) -> None:
    """A status in the donut opens those results; a day of the trend opens that day's results."""
    report = ReportPage(page).open("overview")
    report.wait_for_section("Quality at a glance")
    report.status_legend_link("passed").click()

    report.wait_for_section("Test Results")
    expect(page).to_have_url(re.compile(r"#/results\?status=passed$"))
    expect(report.status_button("passed")).to_have_attribute("aria-pressed", "true")

    page.go_back()
    report.wait_for_section("Quality at a glance")
    report.trend_day_links.last.click()
    report.wait_for_section("Test Results")
    expect(page).to_have_url(re.compile(r"since=2026-10-19&until=2026-10-19"))
    expect(report.remove_chip("Remove From 2026-10-19")).to_be_visible()


def test_a_headline_card_opens_its_evidence(page: Page) -> None:
    """Critical gaps opens Coverage at the gaps; readiness opens its explanation."""
    report = ReportPage(page).open()
    report.wait_for_section("Quality at a glance")
    report.kpi("Critical gaps").click()

    report.wait_for_section("Coverage & Requirements")
    expect(report.gaps).to_be_in_viewport()
    page.go_back()
    report.wait_for_section("Quality at a glance")
    report.kpi("Release readiness").click()
    expect(report.readiness).to_be_in_viewport()
    expect(report.readiness).to_contain_text("no release gate is configured")


# ---- Filters: repository > test type > browser, parent resets, chips ----


def test_test_type_and_browser_follow_the_repository(collected_page: Page) -> None:
    """Only recorded choices; a new test type drops a browser it does not have; chips remove one."""
    page = collected_page
    report = ReportPage(page).open(f"results?{TB_Q}&kind=ui&browser=firefox")
    report.wait_for_section("Test Results")
    expect(report.filter("Browser")).to_have_value("firefox")

    report.filter("Test type").select_option("api")
    report.wait_for_section("Test Results")
    expect(page).not_to_have_url(re.compile("browser="))
    expect(page).to_have_url(re.compile("kind=api"))
    # API runs in one browser only (Electron): no browser choice to make
    expect(report.filter("Browser")).to_have_count(0)

    report.remove_chip(re.compile(r"^Remove Test type")).click()
    expect(page).not_to_have_url(re.compile("kind="))
    report.reset_all()
    expect(page).to_have_url(re.compile(r"#/results$"))


def test_an_unrecorded_combination_says_so(collected_page: Page) -> None:
    """A typed address with a combination no run has is called unsupported, with a reset."""
    page = collected_page
    report = ReportPage(page).open(f"overview?{TB_Q}&kind=performance")
    report.wait_for_section("Quality at a glance")

    expect(page.get_by_text("No collected run has this combination of filters.")).to_be_visible()


# ---- Test details: the exact execution, its context and history ----


@pytest.mark.parametrize("engine", ["chrome", "firefox", "edge"])
def test_a_result_opens_the_execution_of_its_own_browser(collected_page: Page, engine: str) -> None:
    """The same test ran in three browsers: details show the one selected, with its own time."""
    page = collected_page
    report = ReportPage(page).open(f"results?{TB_Q}&kind=ui&browser={engine}&q=combines")
    report.wait_for_section("Test Results")
    row = report.test_rows.first
    time = report.time_of(row)
    row.click()

    expect(report.test_title).to_be_visible()
    expect(page).to_have_url(re.compile(rf"browser={engine}.*job=ui-{engine}.*run=[0-9a-f]{{64}}"))
    expect(report.facts.first).to_contain_text(f"ui-{engine} · {engine}")
    expect(report.execution_time).to_have_text(time)


def test_back_and_shared_links_keep_the_selection(browser: Browser, collected_page: Page) -> None:
    """Back returns to the filtered list; the test's address opens the same execution elsewhere."""
    page = collected_page
    report = ReportPage(page).open(f"results?{TB_Q}&kind=ui&browser=edge&q=combines")
    report.wait_for_section("Test Results")
    report.test_rows.first.click()
    expect(report.test_title).to_be_visible()
    shared = page.url
    ran_in = report.first_fact_value.inner_text()

    report.back_to_results()
    report.wait_for_section("Test Results")
    expect(report.search).to_have_value("combines")
    page.go_back()
    expect(report.test_title).to_be_visible()

    other = browser.new_page()
    other.goto(shared)
    expect(ReportPage(other).first_fact_value).to_have_text(ran_in)
    other.close()


def test_the_search_survives_a_reload(collected_page: Page) -> None:
    """Search and status filter are in the address (replaced while typing, not a new history entry)."""
    page = collected_page
    report = ReportPage(page).open("results")
    report.wait_for_section("Test Results")
    report.search.fill("filters")
    report.status_button("passed").click()
    expect(page).to_have_url(re.compile(r"q=filters&status=passed"))

    page.reload()
    report.wait_for_section("Test Results")
    expect(report.search).to_have_value("filters")
    expect(report.status_button("passed")).to_have_attribute("aria-pressed", "true")


def test_details_tabs_separate_this_execution_history_and_browsers(collected_page: Page) -> None:
    """Keyboard tabs; history in this context apart from all contexts; three browsers compared."""
    page = collected_page
    report = ReportPage(page).open(f"results?{TB_Q}&kind=ui&browser=firefox&q=combines")
    report.wait_for_section("Test Results")
    report.test_rows.first.click()
    report.tab("Selected execution").focus()
    page.keyboard.press("ArrowRight")

    expect(report.tab("History")).to_have_attribute("aria-selected", "true")
    expect(report.tabpanel).to_contain_text("In this context:")
    expect(report.tabpanel).to_contain_text("Across all contexts")
    report.tab("Browser comparison").click()
    expect(report.tabpanel.locator("tbody tr")).to_have_count(3)
    report.tab("Evidence").click()
    expect(report.tabpanel).to_contain_text("Not collected")


def test_long_lists_load_more_and_say_how_many(collected_page: Page) -> None:
    """No silent truncation: 'Showing 50 of 147', then 100 after Load more."""
    report = ReportPage(collected_page).open("results?status=passed")
    report.wait_for_section("Test Results")

    expect(report.list_status).to_have_text("Showing 50 of 147 matching results")
    report.load_more()
    expect(report.list_status).to_have_text("Showing 100 of 147 matching results")
    expect(report.flat_list_rows).to_have_count(100)


def test_the_newest_navigation_wins(collected_page: Page) -> None:
    """Quick section changes: the last one is shown, never an older response."""
    page = collected_page
    report = ReportPage(page).open("results")
    report.wait_for_section("Test Results")
    page.evaluate("location.hash = '#/trends'; location.hash = '#/failures'; location.hash = '#/coverage'")

    report.wait_for_section("Coverage & Requirements")
    page.wait_for_load_state("networkidle")
    expect(report.heading).to_have_text("Coverage & Requirements")
    expect(report.link("Coverage & Requirements", exact=False)).to_have_attribute("aria-current", "page")


def test_earlier_section_names_still_open(page: Page) -> None:
    """Links to the first report version (#/suites, #/categories ...) open the renamed sections."""
    report = ReportPage(page).open("suites")
    report.wait_for_section("Test Results")
    expect(page).to_have_url(re.compile(r"#/results$"))


# ---- Coverage: requirements inside the report ----


def test_a_feature_opens_requirements_and_their_executions_in_scope(page: Page) -> None:
    """Overview feature bar > product opened > requirement page > the exact execution."""
    report = ReportPage(page).open()
    report.wait_for_section("Quality at a glance")
    report.feature("Toolshop").click()

    report.wait_for_section("Coverage & Requirements")
    report.link("SHOP-006", exact=False).click()
    expect(report.heading).to_contain_text("SHOP-006")
    report.open_first_test_case_execution()
    expect(report.test_title).to_be_visible()
    expect(page).to_have_url(re.compile(r"#/test\?.*key=.*run="))


# ---- Data rules on edge cases (skipped-only, failed, recovered, stale, unmapped, untimed) ----


def test_skipped_only_results_are_not_a_pass_rate(edge_page: Page) -> None:
    """The API job only skipped: 'No results' to rate, never 100%."""
    report = ReportPage(edge_page).open("overview?kind=api")
    report.wait_for_section("Quality at a glance")

    expect(report.kpis.first).to_contain_text("No results")
    expect(report.kpis.first).not_to_contain_text("100%")


def test_failures_are_not_product_defects_and_recovered_is_not_unstable(edge_page: Page) -> None:
    """One failed check; one new failure is unstable; the recovered test is listed apart."""
    report = ReportPage(edge_page).open("failures")
    report.wait_for_section("Failures & Stability")

    expect(report.stats.nth(1)).to_contain_text("1unstable tests")
    expect(report.stats.nth(2)).to_contain_text("1recovered")
    expect(edge_page.get_by_text("failed check", exact=True)).to_be_visible()
    expect(report.main).not_to_contain_text("product defect")
    expect(report.recovered).to_contain_text("recovers")


def test_stale_and_incomplete_collections_are_said_plainly(edge_page: Page) -> None:
    """The latest collection is 3 days old and one pipeline was incomplete."""
    report = ReportPage(edge_page).open()
    report.wait_for_section("Quality at a glance")

    expect(report.warning.locator("summary")).to_contain_text("Collection stale")
    expect(report.warning).to_contain_text("Collection incomplete")
    expect(report.freshness).to_contain_text("1 unresolved incomplete collection(s) in 7 days")


def test_unmapped_coverage_and_missing_durations_are_named(edge_page: Page) -> None:
    """Results without requirements: 'Coverage not mapped'; a result without time: 'not recorded'."""
    report = ReportPage(edge_page).open("coverage?repository=e%2Fedge")
    report.wait_for_section("Coverage & Requirements")
    expect(report.unmapped_coverage).to_be_visible()

    report.open("results?q=works")
    report.wait_for_section("Test Results")
    expect(report.test_times.first).to_have_text("not recorded")


# ---- Theme, keyboard, motion, accessibility, phone ----


def test_the_theme_button_works_like_the_portfolio(page: Page) -> None:
    """One button switches light/dark, remembered as na-theme, with the report's dark background."""
    page.emulate_media(color_scheme="light")
    report = ReportPage(page).open()
    report.theme_button("Use dark theme").click()
    page.reload()

    expect(report.document_root).to_have_attribute("data-theme", "dark")
    expect(report.theme_button("Use light theme")).to_be_visible()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == "rgb(17, 27, 43)"


def test_keyboard_focus_is_visible_and_motion_can_be_reduced(page: Page) -> None:
    """A focused link shows an outline; with reduced motion the loading shimmer does not move."""
    page.emulate_media(reduced_motion="reduce")
    report = ReportPage(page).open()
    report.wait_for_section("Quality at a glance")
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
    report = ReportPage(page).open()
    report.set_theme(theme)
    report.open(route)
    page.reload()
    if title:
        report.wait_for_section(title)
    else:
        expect(report.heading).to_be_visible()
        report.wait_until_loaded()
    page.wait_for_load_state("networkidle")

    assert violations(page) == []


@pytest.mark.parametrize(("route", "title"), SECTIONS.items(), ids=list(SECTIONS))
def test_every_section_fits_a_phone(page: Page, route: str, title: str) -> None:
    """390 px: the sidebar becomes a tab row, filters stack, nothing scrolls sideways."""
    page.set_viewport_size({"width": 390, "height": 844})
    report = ReportPage(page).open(route)
    report.wait_for_section(title)
    page.wait_for_load_state("networkidle")

    assert report.fits_the_window()
    assert violations(page) == []


def test_filters_fold_behind_a_toggle_on_a_phone(page: Page) -> None:
    """390 px: the filter bar is one button (with the number of active filters) until opened."""
    page.set_viewport_size({"width": 390, "height": 844})
    report = ReportPage(page).open("results?kind=ui")
    report.wait_for_section("Test Results")
    toggle = report.filter_toggle("Filters (1 active)")

    expect(report.filter("Repository")).to_be_hidden()
    toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")
    expect(report.filter("Repository")).to_be_visible()
