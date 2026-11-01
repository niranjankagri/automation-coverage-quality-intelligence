"""Page object of the report UI at ``/`` (docs/report-ui.md).

The report is one page with sections in the hash route (``#/overview``, ``#/results`` ...). All
its locators live here; the tests keep their assertions.
"""

import re
from typing import Self

from playwright.sync_api import Locator, Page, expect


class ReportPage:
    """The report at ``/``: sections, filters, test details, theme."""

    def __init__(self, page: Page) -> None:
        self.page = page

    # ---- navigation ----

    def open(self, route: str = "") -> Self:
        """Open the report, or a section such as ``results?status=passed``."""
        self.page.goto(f"/#/{route}" if route else "/")
        return self

    def wait_for_section(self, title: str) -> None:
        """Wait until the section's own heading is shown (not the skeleton of another one)."""
        expect(self.heading).to_have_text(title)
        self.wait_until_loaded()

    def wait_until_loaded(self) -> None:
        """Wait until the main area is no longer busy loading."""
        expect(self.main).not_to_have_attribute("aria-busy", "true")

    def set_theme(self, theme: str) -> None:
        """Remember ``light`` or ``dark`` as the chosen theme (read on the next page load)."""
        self.page.evaluate(f"localStorage.setItem('na-theme', '{theme}')")

    def link(self, name: str, *, exact: bool = True) -> Locator:
        """A link by its name, e.g. ``Classic dashboard``."""
        return self.page.get_by_role("link", name=name, exact=exact)

    @property
    def home_link(self) -> Locator:
        """The name/logo link to the report home."""
        return self.page.get_by_role("link", name="Quality Intelligence report home")

    @property
    def document_root(self) -> Locator:
        """The html element (carries the chosen theme in ``data-theme``)."""
        return self.page.locator("html")

    @property
    def main(self) -> Locator:
        """The main area."""
        return self.page.locator("main")

    @property
    def heading(self) -> Locator:
        """The h1 of the current section."""
        return self.page.locator("main h1")

    def fits_the_window(self) -> bool:
        """Whether the page is no wider than the window (no sideways scrolling)."""
        return bool(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))

    # ---- overview ----

    @property
    def kpis(self) -> Locator:
        """The headline cards (pass rate, automation coverage, critical gaps, readiness)."""
        return self.page.locator(".kpi")

    def kpi(self, name: str) -> Locator:
        """The headline card containing ``name``, e.g. ``Critical gaps``."""
        return self.kpis.filter(has_text=name)

    @property
    def big_number(self) -> Locator:
        """The large number in the middle of the status ring (test executions)."""
        return self.page.locator(".big-number")

    @property
    def passed_ring_segment(self) -> Locator:
        """The passed segment of the status ring."""
        return self.page.locator(".ring .seg-passed")

    @property
    def browser_comparison(self) -> Locator:
        """The exact per-browser comparison table."""
        return self.page.locator(".compare")

    @property
    def browser_comparison_rows(self) -> Locator:
        """The rows of the per-browser comparison."""
        return self.page.locator(".compare tbody tr")

    def show_exact_browser_numbers(self) -> None:
        """Unfold "Compare exact numbers"."""
        self.page.get_by_text("Compare exact numbers", exact=True).click()

    def browser_card(self, browser: str) -> Locator:
        """The first browser card containing ``browser``."""
        return self.page.locator("a.browser-card").filter(has_text=browser).first

    @property
    def scope(self) -> Locator:
        """The "Selected scope" region (repositories with their outcomes)."""
        return self.page.get_by_role("region", name="Selected scope", exact=True)

    @property
    def scope_links(self) -> Locator:
        """The repository links of the scope."""
        return self.scope.locator(".suite-name a")

    def status_legend_link(self, status: str) -> Locator:
        """The legend link of one status in the status ring, e.g. ``passed``."""
        return self.page.locator(".legend a").filter(has_text=status)

    @property
    def trend_day_links(self) -> Locator:
        """The day links of the trend chart."""
        return self.page.locator(".chart a")

    def feature(self, name: str) -> Locator:
        """A feature bar of the overview, e.g. ``Toolshop``."""
        return self.page.locator(".feature-name").filter(has_text=name)

    @property
    def gaps(self) -> Locator:
        """The critical gaps part of the coverage section."""
        return self.page.locator("#gaps")

    @property
    def readiness(self) -> Locator:
        """The release readiness explanation."""
        return self.page.locator("#readiness")

    @property
    def warning(self) -> Locator:
        """The collection warning notice."""
        return self.page.locator(".notice-warning")

    @property
    def freshness(self) -> Locator:
        """The data freshness line."""
        return self.page.locator(".freshness")

    # ---- filters ----

    def filter(self, label: str) -> Locator:
        """A filter by its label, e.g. ``Browser`` or ``Test type``."""
        return self.page.get_by_label(label, exact=True)

    def status_button(self, status: str) -> Locator:
        """The status filter button whose name starts with ``status``, e.g. ``passed``."""
        return self.page.get_by_role("button", name=re.compile(f"^{status}"))

    def remove_chip(self, name: str | re.Pattern[str], *, exact: bool | None = None) -> Locator:
        """The remove button of an active filter chip, e.g. ``Remove Browser chromium``."""
        return self.page.get_by_role("button", name=name, exact=exact)

    def reset_all(self) -> None:
        """Click Reset all."""
        self.page.get_by_role("button", name="Reset all").click()

    def filter_toggle(self, name: str) -> Locator:
        """The phone-width filters button, e.g. ``Filters (1 active)``."""
        return self.page.get_by_role("button", name=name)

    # ---- results ----

    @property
    def search(self) -> Locator:
        """The Search tests field."""
        return self.page.get_by_label("Search tests")

    @property
    def test_rows(self) -> Locator:
        """The result rows."""
        return self.page.locator(".test-row")

    @property
    def flat_list_rows(self) -> Locator:
        """The result rows of the flat (ungrouped) list."""
        return self.page.locator(".flat-list .test-row")

    @property
    def test_times(self) -> Locator:
        """The time column of the result rows."""
        return self.page.locator(".test-time")

    @staticmethod
    def time_of(row: Locator) -> str:
        """The time shown in a result row."""
        return row.locator(".test-time").inner_text()

    @property
    def list_status(self) -> Locator:
        """The "Showing N of M" line."""
        return self.page.locator(".list-status")

    def load_more(self) -> None:
        """Click Load more."""
        self.page.get_by_role("button", name="Load more").click()

    @property
    def unmapped_coverage(self) -> Locator:
        """The "Coverage not mapped" empty state."""
        return self.page.locator("[data-empty='not-mapped']")

    @property
    def stats(self) -> Locator:
        """The numbers at the top of Failures & Stability."""
        return self.page.locator(".stat")

    @property
    def recovered(self) -> Locator:
        """The recovered tests section."""
        return self.page.locator("section[aria-labelledby='f-recovered']")

    # ---- test and requirement details ----

    @property
    def test_title(self) -> Locator:
        """The title of a test's details."""
        return self.page.locator(".test-title")

    @property
    def facts(self) -> Locator:
        """The facts lists of a test's details."""
        return self.page.locator(".facts")

    @property
    def first_fact_value(self) -> Locator:
        """The first value of the facts list (where the execution ran)."""
        return self.page.locator(".facts dd").first

    @property
    def execution_time(self) -> Locator:
        """The time in the selected execution's heading."""
        return self.page.locator(".execution-head strong")

    def back_to_results(self) -> None:
        """Follow "← Back to results"."""
        self.page.get_by_role("link", name="← Back to results").click()

    def tab(self, name: str) -> Locator:
        """A tab of a test's details, e.g. ``History``."""
        return self.page.get_by_role("tab", name=name)

    @property
    def tabpanel(self) -> Locator:
        """The visible tab panel."""
        return self.page.get_by_role("tabpanel")

    def open_first_test_case_execution(self) -> None:
        """On a requirement page: open the first execution of its first test case."""
        self.page.locator(".test-case tbody a").first.click()

    # ---- theme ----

    def theme_button(self, name: str) -> Locator:
        """The theme switch, named after what it does, e.g. ``Use dark theme``."""
        return self.page.get_by_role("button", name=name)
