"""Page objects of the classic dashboard at ``/classic/`` (docs/dashboard.md).

Every locator of the classic dashboard lives here, so a changed selector is fixed in one place and
the tests read as what a user does and sees. The page objects find elements and perform actions;
the tests keep their assertions (``expect(...)``), so a failure still points at the test's check.

``ClassicPage`` is the shell every screen shares (header, navigation, filters, data bar); each
screen adds its own parts in a subclass and names its address in ``ROUTE``.
"""

import re
from pathlib import Path
from typing import Self

from playwright.sync_api import Locator, Page


class ClassicPage:
    """The shared shell of every classic screen: header, navigation, filters, data bar, view."""

    # Address of the screen inside /classic/ (the hash route); subclasses set their own
    ROUTE = "#/coverage"

    def __init__(self, page: Page) -> None:
        self.page = page

    # ---- navigation ----

    def open(self, route: str | None = None) -> Self:
        """Open this screen, or ``route`` (e.g. ``#/runs?framework=pytest``) inside /classic/."""
        self.page.goto(f"/classic/{self.ROUTE if route is None else route}")
        return self

    def set_theme(self, theme: str) -> None:
        """Remember ``light`` or ``dark`` as the chosen theme (read on the next page load)."""
        self.page.evaluate(f"localStorage.setItem('qi-theme', '{theme}')")

    def nav_link(self, name: str) -> Locator:
        """A link with exactly this name, e.g. ``Runs`` in the navigation."""
        return self.page.get_by_role("link", name=name, exact=True)

    def go_to(self, name: str) -> None:
        """Follow the link named exactly ``name``, e.g. ``Requirements``."""
        self.nav_link(name).click()

    @property
    def section_nav(self) -> Locator:
        """The grouped navigation (Investigate, Coverage, Execution, Analytics, Operations)."""
        return self.page.locator(".section-nav")

    def section_link(self, nav_id: str) -> Locator:
        """The navigation link of one section by its ``data-nav`` name, e.g. ``overview``."""
        return self.page.locator(f'.section-nav a[data-nav="{nav_id}"]')

    @property
    def section_links(self) -> Locator:
        """All links of the Sections navigation."""
        return self.page.locator("nav[aria-label=Sections] a")

    @property
    def mobile_sections_toggle(self) -> Locator:
        """The phone-width button that opens and closes the whole navigation."""
        return self.page.locator(".mobile-nav > summary")

    @property
    def breadcrumb(self) -> Locator:
        """The breadcrumb trail above the content."""
        return self.page.get_by_role("navigation", name="Breadcrumb")

    @property
    def back_to_filtered_results(self) -> Locator:
        """The link back to the filtered list a detail page was opened from."""
        return self.page.get_by_role("link", name="Back to filtered results")

    @property
    def skip_link(self) -> Locator:
        """The "Skip to content" link, the first stop of the Tab key."""
        return self.page.get_by_role("link", name="Skip to content")

    @property
    def document_root(self) -> Locator:
        """The html element (carries the chosen theme in ``data-theme``)."""
        return self.page.locator("html")

    @property
    def body(self) -> Locator:
        """The body element (carries the ``compact`` density class)."""
        return self.page.locator("body")

    @property
    def main(self) -> Locator:
        """The main region (the skip link moves focus here)."""
        return self.page.locator("main")

    def layout_regions(self) -> dict[str, Locator]:
        """The page regions from top to bottom (header, filters, data bar, notice, content)."""
        selectors = ["header.top", "#filters", ".databar", "#catalog-notice", "main"]
        return {selector: self.page.locator(selector).first for selector in selectors}

    # ---- header: search, theme, density, guide ----

    @property
    def header_search(self) -> Locator:
        """The search box in the header."""
        return self.page.get_by_role("searchbox", name=re.compile("^Search tests, requirements"))

    def search_from_header(self, text: str) -> None:
        """Type ``text`` into the header search and press Enter."""
        self.header_search.fill(text)
        self.header_search.press("Enter")

    @property
    def theme_select(self) -> Locator:
        """The Theme select (system, light, dark)."""
        return self.page.get_by_label("Theme")

    @property
    def compact_checkbox(self) -> Locator:
        """The Compact density checkbox."""
        return self.page.get_by_label("Compact")

    def open_guide(self) -> None:
        """Open the first-use guide and glossary dialog."""
        self.page.get_by_role("button", name="Guide and glossary").click()

    @property
    def guide_dialog(self) -> Locator:
        """The guide and glossary dialog."""
        return self.page.get_by_role("dialog", name="Dashboard guide and glossary")

    def close_guide(self) -> None:
        """Close the guide dialog."""
        self.page.get_by_role("button", name="Close guide").click()

    # ---- filters ----

    @property
    def filters(self) -> Locator:
        """The filter form."""
        return self.page.locator("#filters")

    def filter_select(self, name: str) -> Locator:
        """A select of the filter form by its ``name``, e.g. ``repository`` or ``framework``."""
        return self.page.locator(f'#filters select[name="{name}"]')

    @property
    def filter_panel_toggle(self) -> Locator:
        """The summary that folds the filter area."""
        return self.page.locator("#filter-panel > summary")

    @property
    def advanced_filters_button(self) -> Locator:
        """The button that shows or hides the advanced filters."""
        return self.page.get_by_role("button", name="Advanced filters", exact=True)

    @property
    def active_filters(self) -> Locator:
        """The area that lists the active filters."""
        return self.page.locator("#active-filters")

    @property
    def active_filter_chips(self) -> Locator:
        """The list of active filters as removable chips."""
        return self.page.get_by_role("list", name="Active filters")

    def remove_filter(self, chip: str) -> None:
        """Remove the active filter shown as ``chip``, e.g. ``Framework: testng``."""
        self.page.get_by_role("button", name=f"Remove filter {chip}").click()

    def quick_range(self, name: str) -> None:
        """Click a quick date range button, e.g. ``30 days`` or ``All dates``."""
        self.page.get_by_role("button", name=name).click()

    def preset(self, name: str) -> None:
        """Click a quick view (preset) button, e.g. ``Critical gaps``."""
        self.page.get_by_role("button", name=name).click()

    def clear_filters(self) -> None:
        """Click Clear."""
        self.page.get_by_role("button", name="Clear").click()

    # ---- data bar: freshness, refresh, notices ----

    @property
    def data_fresh(self) -> Locator:
        """The "Data loaded ..." freshness line."""
        return self.page.locator("#data-fresh")

    @property
    def data_stale(self) -> Locator:
        """The warning shown when the last refresh failed."""
        return self.page.locator("#data-stale")

    @property
    def data_size(self) -> Locator:
        """The data size line, e.g. "42 requirements"."""
        return self.page.locator("#data-size")

    @property
    def catalog_notice(self) -> Locator:
        """The notice above every page (e.g. that the sample catalog is synthetic)."""
        return self.page.locator("#catalog-notice")

    def refresh(self) -> None:
        """Click Refresh (reload the data without reloading the page)."""
        self.page.get_by_role("button", name="Refresh").click()

    # ---- the view: what the current screen shows ----

    @property
    def view(self) -> Locator:
        """The content area of the current screen."""
        return self.page.locator("#view")

    @property
    def view_heading(self) -> Locator:
        """The h1 of the current screen."""
        return self.page.locator("#view h1")

    def heading(self, name: str | re.Pattern[str], *, exact: bool = True) -> Locator:
        """A heading by its name, e.g. ``Overview``."""
        return self.page.get_by_role("heading", name=name, exact=exact)

    @property
    def rows(self) -> Locator:
        """The body rows of the tables in the view."""
        return self.page.locator("#view tbody tr")

    @property
    def tables(self) -> Locator:
        """The tables in the view."""
        return self.page.locator("#view table")

    @property
    def alert(self) -> Locator:
        """Error messages (role alert) anywhere on the page."""
        return self.page.get_by_role("alert")

    @property
    def view_alerts(self) -> Locator:
        """Error messages inside the view."""
        return self.page.locator("#view [role=alert]")

    @property
    def note(self) -> Locator:
        """Notes (role note) anywhere on the page."""
        return self.page.get_by_role("note")

    @property
    def view_notes(self) -> Locator:
        """Notes inside the view."""
        return self.page.locator("#view [role=note]")

    def retry(self) -> None:
        """Click Retry after an error."""
        self.page.get_by_role("button", name="Retry").click()

    @property
    def charts(self) -> Locator:
        """All charts of the view."""
        return self.page.locator("figure.chart")

    def chart(self, title: str) -> Locator:
        """The chart whose text contains ``title``, e.g. ``Test results``."""
        return self.charts.filter(has_text=title)

    @property
    def pagers(self) -> Locator:
        """The table pagers ("Rows 1-50 of 120", Previous/Next)."""
        return self.page.locator(".pagerbox")

    def region(self, name: str | re.Pattern[str], *, exact: bool = False) -> Locator:
        """A named region, e.g. ``Requirement list``."""
        return self.page.get_by_role("region", name=name, exact=exact)

    def copy(self, what: str) -> None:
        """Click a copy button, e.g. ``Copy summary (text)``."""
        self.page.get_by_role("button", name=what).click()

    @property
    def copied(self) -> Locator:
        """The "Copied" confirmation a copy button turns into."""
        return self.page.get_by_role("button", name="Copied")

    def clipboard_text(self) -> str:
        """What the browser's clipboard holds (needs the clipboard permissions)."""
        return str(self.page.evaluate("navigator.clipboard.readText()"))

    def scroll_overflow(self) -> int:
        """How many pixels the page scrolls sideways (0 or less = it does not)."""
        return int(
            self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        )

    def fits_the_window(self) -> bool:
        """Whether the page is no wider than the window (no sideways scrolling)."""
        return bool(self.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"))


def card_in(page: Page, label: str) -> Locator:
    """The metric card whose label is exactly ``label`` (used on several screens)."""
    return page.locator(".card").filter(
        has=page.locator(".label", has_text=re.compile(f"^{re.escape(label)}$"))
    )


class OverviewPage(ClassicPage):
    """Coverage & release overview: metric cards, gaps, release status, quick views."""

    ROUTE = "#/coverage"

    def card(self, label: str) -> Locator:
        """The overview card whose label is exactly ``label``, e.g. ``Requirement coverage``."""
        return card_in(self.page, label)

    def card_help(self, label: str) -> Locator:
        """The card frame with the help tip of the card labelled ``label``."""
        return self.page.locator(".card-shell").filter(has=self.page.locator(".label", has_text=label))

    def open_card_help(self, label: str) -> Locator:
        """Open the help tip of the card labelled ``label``; returns its popover."""
        shell = self.card_help(label)
        shell.locator(".help-tip > summary").click()
        return shell.locator(".help-popover")

    @property
    def critical_requirements(self) -> Locator:
        """The chips under "Critical requirements without automation"."""
        return self.page.locator("h2:has-text('Critical requirements without automation') + ul.chips")

    @property
    def gap_owners(self) -> Locator:
        """One folding block per owner under "Coverage gaps by owner"."""
        return self.page.locator("details.gap-owner")

    @property
    def open_gap_owners(self) -> Locator:
        """The owner blocks that are unfolded."""
        return self.page.locator("details.gap-owner[open]")

    @property
    def release_status(self) -> Locator:
        """The Release status panel."""
        return self.region("Release status")

    @property
    def criticality(self) -> Locator:
        """The Criticality filter."""
        return self.page.get_by_label("Criticality")

    def change_summary(self) -> Locator:
        """The build comparison's change summary, or its "No change summary shown" explanation."""
        return self.page.get_by_text(re.compile("Observed changes from .* across .* shared suite")).or_(
            self.page.get_by_text("No change summary shown", exact=False)
        )


class RequirementsPage(ClassicPage):
    """The requirement list, the matrix and the repository breakdown."""

    ROUTE = "#/requirements"

    @property
    def requirement_rows(self) -> Locator:
        """The rows of the requirement list."""
        return self.region("Requirement list").locator("tbody tr")

    @property
    def status(self) -> Locator:
        """The Status filter (e.g. ``no tests``)."""
        return self.page.get_by_label("Status")

    @property
    def repository_rows(self) -> Locator:
        """The rows of the "Observed requirements" table, one per repository."""
        return (
            self.page.locator(".table-block table")
            .filter(has_text="Observed requirements")
            .locator("tbody tr")
        )


class TestsPage(ClassicPage):
    """The test list."""

    ROUTE = "#/tests"
    # Not a test class, although the name starts with "Test" (pytest must not collect it)
    __test__ = False

    @property
    def outcome_filter(self) -> Locator:
        """The outcome filter of the test list (e.g. ``failed``)."""
        return self.page.locator("#outcome-filter")

    def open_test(self, name: str) -> "TestDetailPage":
        """Filter the list by ``name`` and open the test whose link contains it."""
        self.page.get_by_label("Filter tests by name").fill(name)
        self.page.get_by_role("link", name=re.compile(name)).click()
        return TestDetailPage(self.page)


class TestDetailPage(ClassicPage):
    """One test's investigation page: latest result, pattern, executions, comparison."""

    ROUTE = "#/test"
    __test__ = False

    def open_key(self, key: str) -> Self:
        """Open the page of the test with identifier ``key``."""
        return self.open(f"#/test?key={key}")

    @property
    def execution_rows(self) -> Locator:
        """The rows of the Executions table."""
        return self.region(re.compile("^Executions")).locator("tbody tr")

    @property
    def failed_execution_rows(self) -> Locator:
        """The executions marked failed."""
        return self.execution_rows.filter(has=self.page.locator(".badge.failed"))

    @staticmethod
    def expand(row: Locator) -> Locator:
        """Unfold the failure message of an execution row; returns its stack trace."""
        row.locator("summary").click()
        return row.locator("pre.trace")

    @property
    def meta(self) -> Locator:
        """The facts list at the top (latest result, pattern)."""
        return self.page.locator("dl.meta")

    @property
    def pattern(self) -> Locator:
        """One item per execution in the result pattern."""
        return self.meta.locator("ol.pattern li")

    @property
    def comparison(self) -> Locator:
        """The "Compare two executions" section."""
        return self.region("Compare two executions")

    @property
    def execution_a(self) -> Locator:
        """The select of the first execution to compare."""
        return self.page.get_by_label("Execution A")

    def comparison_row(self, name: str) -> Locator:
        """The comparison row whose name starts with ``name``, e.g. ``Outcome``."""
        return self.comparison.get_by_role("row", name=re.compile(f"^{name}"))


class RunsPage(ClassicPage):
    """The run list and one run's page."""

    ROUTE = "#/runs"

    def row_with(self, text: str) -> Locator:
        """The table row containing ``text``."""
        return self.page.get_by_role("row").filter(has_text=text)

    def open_run(self, name: str | re.Pattern[str]) -> None:
        """Open the run whose link name matches ``name``."""
        self.page.get_by_role("link", name=name).click()

    def sort_by(self, column: str) -> None:
        """Click the sort button of the column whose name starts with ``column``."""
        self.page.get_by_role("button", name=re.compile(f"^{column}")).click()

    @property
    def ascending_headers(self) -> Locator:
        """Column headers currently sorted ascending."""
        return self.page.locator("#view th[aria-sort=ascending]")

    def cell(self, row: Locator, column: int) -> Locator:
        """Cell number ``column`` (from 0) of ``row``."""
        return row.locator("td").nth(column)

    def filter_rows(self, text: str) -> None:
        """Type into the table's row filter."""
        self.page.get_by_label("Filter rows").fill(text)

    def download_csv(self) -> str:
        """Click Download CSV and return the downloaded file's text."""
        with self.page.expect_download() as download:
            self.page.get_by_role("button", name="Download CSV").click()
        return Path(download.value.path()).read_text(encoding="utf-8")

    @property
    def run_meta(self) -> Locator:
        """The facts list of a run's page."""
        return self.page.locator("dl.meta")


class StabilityPage(ClassicPage):
    """Flaky candidates, their evidence, and issue drafts for recurring failures."""

    ROUTE = "#/stability"

    def card(self, label: str) -> Locator:
        """The card whose label is exactly ``label``, e.g. ``Flaky candidate``."""
        return card_in(self.page, label)

    def row_with(self, text: str) -> Locator:
        """The table rows containing ``text``."""
        return self.rows.filter(has_text=text)

    @property
    def strips(self) -> Locator:
        """The result strips, one per flaky candidate."""
        return self.page.locator("ol.strip")

    @property
    def window(self) -> Locator:
        """The Window select (how many runs count)."""
        return self.page.get_by_label("Window")

    def draft(self, title: str) -> Locator:
        """The issue draft whose summary contains ``title``."""
        return self.page.locator("details", has_text=title)

    def open_draft(self, title: str) -> Locator:
        """Unfold the issue draft whose summary contains ``title``; returns the draft."""
        draft = self.draft(title)
        draft.locator("summary").click()
        return draft


class TrendsPage(ClassicPage):
    """Daily trends: charts, their number tables, the date range."""

    ROUTE = "#/trends"

    @property
    def date_from(self) -> Locator:
        """The From date."""
        return self.page.get_by_label("From", exact=True)

    @property
    def date_to(self) -> Locator:
        """The To date."""
        return self.page.get_by_label("To", exact=True)

    def number_rows(self, title: str) -> Locator:
        """Open "Show the numbers" of the chart ``title``; returns the rows of its table."""
        chart = self.chart(title)
        chart.get_by_text("Show the numbers").click()
        return chart.locator("tbody tr")

    def day_bar(self, day: str) -> Locator:
        """The bar link of one day, e.g. ``10-13``."""
        return self.page.get_by_role("link", name=re.compile(f"^{day}: .*Open the runs"))


class PipelinesPage(ClassicPage):
    """Pipeline executions with their jobs, expected jobs and status chips."""

    ROUTE = "#/pipelines"

    @property
    def pipelines(self) -> Locator:
        """One folding block per pipeline execution."""
        return self.page.locator("details.pipeline")

    def pipeline(self, text: str) -> Locator:
        """The pipeline block containing ``text``, e.g. ``Pipeline 39238241112``."""
        return self.pipelines.filter(has_text=text)

    @staticmethod
    def badge(pipeline: Locator) -> Locator:
        """The complete/incomplete badge of a pipeline block."""
        return pipeline.locator("summary .badge")

    @staticmethod
    def expand(pipeline: Locator) -> None:
        """Unfold a pipeline block (its jobs and problems)."""
        pipeline.locator("summary").click()

    @staticmethod
    def missing_jobs(pipeline: Locator) -> Locator:
        """The rows of expected jobs that have no results."""
        return pipeline.locator("tr.missing")

    def expect_jobs(self, jobs: str) -> None:
        """Enter the expected jobs, e.g. ``api, ui-chrome``, and confirm with Enter."""
        field = self.page.get_by_label("Expected jobs")
        field.fill(jobs)
        field.press("Enter")

    @property
    def status_chips(self) -> Locator:
        """The status chips (All, complete, incomplete)."""
        return self.page.get_by_role("navigation", name="Pipeline status")


class ComparePage(ClassicPage):
    """Build comparison."""

    ROUTE = "#/compare"

    @property
    def baseline(self) -> Locator:
        """The baseline build select."""
        return self.page.get_by_label("Baseline build")

    @property
    def comparison_build(self) -> Locator:
        """The comparison build select."""
        return self.page.get_by_label("Comparison build")

    @property
    def change_types(self) -> Locator:
        """The change type chips (slower, faster, new failure ...)."""
        return self.page.get_by_role("navigation", name="Change type")

    def open_first_test(self) -> None:
        """Open the first test of the change list."""
        self.page.locator("#view tbody tr a.key").first.click()

    @property
    def cards(self) -> Locator:
        """The two build cards."""
        return self.page.locator("#view .card")


class AttentionPage(ClassicPage):
    """Needs attention: findings with their evidence, grouped by what to do."""

    ROUTE = "#/attention"

    @property
    def findings(self) -> Locator:
        """The finding rows."""
        return self.page.locator("#view table tbody tr")

    def show_state(self, state: str) -> None:
        """Click the finding state chip matching ``state``, e.g. ``suspected``."""
        self.page.get_by_role("navigation", name="Finding state").get_by_role(
            "link", name=re.compile(state)
        ).click()

    def group(self, name: str) -> Locator:
        """The action group containing ``name``, e.g. ``Investigate now``."""
        return self.page.locator(".action-group").filter(has_text=name)


class CollectionPage(ClassicPage):
    """Operations: dashboard snapshot, collection health per repository, problems."""

    ROUTE = "#/collection"

    def problem(self, text: str) -> Locator:
        """The collection problem containing ``text``."""
        return self.page.locator("ul.reasons li").filter(has_text=text)

    def repository_row(self, repository: str) -> Locator:
        """The table row of ``repository``."""
        return self.page.get_by_role("row").filter(has_text=repository)


class SearchPage(ClassicPage):
    """Search across tests, requirements and pipelines."""

    ROUTE = "#/search"

    @property
    def box(self) -> Locator:
        """The "Search for" field."""
        return self.page.get_by_label("Search for")

    @property
    def results(self) -> Locator:
        """The search results area."""
        return self.page.locator("#search-results")

    def result_group(self, name: str) -> Locator:
        """The result region whose name starts with ``name``, e.g. ``Tests``."""
        return self.region(re.compile(f"^{name}"))


class ExecutionsPage(ClassicPage):
    """The execution dashboard (the classic landing page)."""

    ROUTE = "#/executions"

    @property
    def suite(self) -> Locator:
        """The suite select."""
        return self.page.locator("#execution-suite")

    @property
    def suite_options(self) -> Locator:
        """The options of the suite select."""
        return self.page.locator("#execution-suite option")

    @property
    def limit(self) -> Locator:
        """The "Top N" select."""
        return self.page.locator("#execution-limit")

    @property
    def first_ranked_test(self) -> Locator:
        """The first test link in the rankings."""
        return self.page.locator(".execution-panel a.key").first

    @property
    def cards(self) -> Locator:
        """The summary cards."""
        return self.page.locator(".execution-cards")

    @property
    def rankings(self) -> Locator:
        """The folding ranking tables."""
        return self.page.locator(".ranking-details")

    def open_first_ranking(self) -> None:
        """Unfold the first ranking table."""
        self.page.locator(".ranking-details > summary").first.click()

    def choice(self, step: str, option: str) -> Locator:
        """A button of a guided step, e.g. ``choice("Choose a browser", "chrome")``."""
        return self.region(step, exact=True).get_by_role("button", name=option, exact=True)

    @property
    def status_buttons(self) -> Locator:
        """The status buttons of the donut chart."""
        return self.page.get_by_role("group", name="Explore result status")

    @property
    def donut_selection(self) -> Locator:
        """What the donut chart says is selected."""
        return self.page.locator(".donut-selection")

    @property
    def back_to_portfolio(self) -> Locator:
        """The link back to the portfolio site."""
        return self.page.get_by_role("link", name="← Back to portfolio")

    def reset_chart(self) -> None:
        """Click Reset chart."""
        self.page.get_by_role("button", name="Reset chart", exact=True).click()

    def open_first_day(self) -> None:
        """Click the first day of the daily chart."""
        self.page.get_by_role("group", name="Bars, one link per day").get_by_role("link").first.click()
