"""M12 investigation workflow in a real browser: search, needs attention, drill-down, compare, copy.

Runs on the sample results (the dashboard of the demonstration) and on the collected TaskBoard
pipelines (with collection records, as a collecting deployment has them).
"""

import os
import re

import pytest
from pages.classic import (
    AttentionPage,
    ComparePage,
    OverviewPage,
    PipelinesPage,
    SearchPage,
    StabilityPage,
    TestDetailPage,
)
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ENGINE = os.environ.get("QI_E2E_BROWSER", "chromium")
TEST_KEY = "com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer"


def test_the_header_search_finds_a_test_and_opens_its_history(page: Page) -> None:
    """Keyboard only: focus the header search, type, Enter; the result opens the test's page."""
    overview = OverviewPage(page).open()
    expect(overview.heading("Overview")).to_be_visible()
    overview.header_search.focus()
    page.keyboard.type("adminEditsACustomer")
    page.keyboard.press("Enter")

    expect(page).to_have_url(re.compile(r"#/search\?q=adminEditsACustomer"))
    results = SearchPage(page).result_group("Tests")
    expect(results.get_by_role("link", name=TEST_KEY)).to_be_visible()
    expect(results.locator("mark").first).to_have_text(re.compile("adminEditsACustomer", re.IGNORECASE))
    results.get_by_role("link", name=TEST_KEY).click()

    expect(overview.view_heading).to_have_text(TEST_KEY)
    expect(overview.breadcrumb).to_contain_text("Tests")


def test_search_follows_typing_keeps_the_query_in_the_address_and_explains_no_results(page: Page) -> None:
    """Debounced: the address follows the input; a reload restores it; nothing found says why."""
    search = SearchPage(page).open()
    expect(search.results).to_contain_text("at least two characters")
    search.box.fill("SHOP-006")

    expect(page).to_have_url(re.compile(r"q=SHOP-006"))
    expect(search.result_group("Requirements").get_by_role("link", name="SHOP-006")).to_be_visible()
    page.reload()
    expect(search.box).to_have_value("SHOP-006")
    search.box.fill("zzz-no-such-thing")
    expect(search.results).to_contain_text("Nothing matches")


def test_search_highlight_maps_unicode_lowercase_expansion_to_original_text(page: Page) -> None:
    """Lowercasing U+0130 adds a code point; the highlight must still cover the original letter."""
    OverviewPage(page).open()
    highlighted = page.evaluate(
        """() => {
          const wrapper = document.createElement('span');
          wrapper.append(...highlight('İstanbul', ['i\\u0307']));
          return { text: wrapper.textContent, mark: wrapper.querySelector('mark')?.textContent };
        }"""
    )

    assert highlighted == {"text": "İstanbul", "mark": "İ"}


def test_search_results_keep_the_repository_filter(collected_page: Page) -> None:
    """With a repository chosen, results and their links stay in that repository."""
    page = collected_page
    pipelines = PipelinesPage(page).open()
    pipelines.filter_select("repository").select_option(index=1)
    repository = pipelines.filter_select("repository").input_value()
    pipelines.search_from_header("38842296207")

    hit = SearchPage(page).result_group("Pipelines").get_by_role("link", name="38842296207")
    expect(hit).to_have_attribute(
        "href", re.compile(f"repository={re.escape(repository).replace('/', '%2F')}")
    )
    hit.click()
    expect(pipelines.note.filter(has_text="Showing pipeline")).to_contain_text("38842296207 only")
    expect(pipelines.pipelines).to_have_count(1)


def test_needs_attention_lists_evidence_and_leads_to_the_records(page: Page) -> None:
    """Every finding says why and how much evidence; states filter; a finding opens its test."""
    attention = AttentionPage(page).open()
    expect(attention.heading("Needs attention", exact=False)).to_be_visible()
    rows = attention.findings
    expect(rows.first).to_be_visible()
    assert rows.count() >= 8  # 2 critical gaps, 2 confirmed slowdowns, 4 flaky candidates in the samples

    attention.show_state("suspected")
    expect(page).to_have_url(re.compile("state=suspected"))
    expect(rows).to_have_count(4)
    expect(rows.first).to_contain_text("flaky candidate")
    rows.first.get_by_role("link").first.click()
    expect(attention.view_heading).to_have_class(re.compile("key"))


def test_an_incomplete_pipeline_finding_links_its_pipeline_and_github_run(collected_page: Page) -> None:
    """The cancelled TaskBoard run: open, with the reason, the pipeline here and the run on GitHub."""
    page = collected_page
    attention = AttentionPage(page).open()
    row = attention.findings.filter(has_text="incomplete pipeline")

    expect(row).to_contain_text("artifact report-ui-firefox not found")
    expect(row.get_by_role("link", name="GitHub run")).to_have_attribute(
        "href", re.compile(r"^https://github\.com/.+/attempts/1$")
    )
    row.get_by_role("link", name=re.compile("38842296207")).click()
    expect(PipelinesPage(page).pipelines).to_have_count(1)
    expect(attention.breadcrumb).to_contain_text("38842296207")


def test_the_investigation_compares_two_executions(page: Page) -> None:
    """Choose two executions of a test: outcome, build, duration, failure side by side."""
    test = TestDetailPage(page).open_key(TEST_KEY)
    expect(test.comparison.locator("tbody")).to_contain_text("Outcome")

    options = test.execution_a.locator("option")
    failed = next(i for i in range(options.count()) if options.nth(i).inner_text().endswith("failed"))
    test.execution_a.select_option(str(failed))
    expect(test.comparison_row("Outcome")).to_contain_text("failed")
    failure_of_a = test.comparison_row("Failure").locator("td").first
    expect(failure_of_a).not_to_have_text("none recorded")


@pytest.mark.skipif(ENGINE != "chromium", reason="clipboard permissions are a Chromium feature")
def test_summaries_are_copied_as_text_and_markdown(page: Page) -> None:
    """The test page and the build comparison copy the server's summary, with its limitations."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    test = TestDetailPage(page).open_key(TEST_KEY)
    expect(test.view_heading).to_have_text(TEST_KEY)
    test.copy("Copy summary (text)")
    expect(test.copied).to_be_visible()
    text = test.clipboard_text()
    assert text.startswith(f"Investigation: {TEST_KEY}")
    assert "Limitations:" in text
    assert "flaky candidate (suspected)" in text

    compare = ComparePage(page).open("#/compare?framework=testng&base=f5a40d5&head=1d03232")
    expect(compare.heading("Compare builds", exact=False)).to_be_visible()  # not the test page's button
    compare.copy("Copy summary (Markdown)")
    expect(compare.copied).to_be_visible()
    markdown = compare.clipboard_text()
    assert markdown.startswith("### Build comparison: f5a40d5 vs 1d03232")
    assert "**Limitations**" in markdown


def test_the_comparison_shows_count_differences_and_evidence(page: Page) -> None:
    """Count differences per outcome; builds without collection records say so instead of a link."""
    compare = ComparePage(page).open("#/compare?framework=testng&base=f5a40d5&head=1d03232")

    expect(compare.view).to_contain_text("Result counts, comparison minus baseline")
    expect(compare.cards.first).to_contain_text("no GitHub run recorded")


def test_a_recurring_failure_has_a_draft_that_github_submits_not_the_dashboard(
    recurring_page: Page,
) -> None:
    """Stability: the draft shows its evidence; the GitHub link only opens the pre-filled form."""
    stability = StabilityPage(recurring_page).open()
    expect(stability.heading("Issue drafts for recurring failures (1)", exact=False)).to_be_visible()

    draft = stability.open_draft("#1 Recurring test failure: TimeoutError")

    body = draft.get_by_role("textbox", name=re.compile("Draft body"))
    expect(body).to_have_value(re.compile(r"Seen in \*\*2 runs\*\*"))
    expect(body).to_have_value(re.compile(r"\[CI run\]\(https://github\.com/o/r/actions/runs/19\)"))
    expect(body).to_have_attribute("readonly", "")
    submit = draft.get_by_role("link", name="Review and submit on GitHub")
    expect(submit).to_have_attribute("href", re.compile(r"^https://github\.com/o/r/issues/new\?title="))
    expect(submit).to_have_attribute("rel", "noopener noreferrer")
    expect(draft.get_by_role("button", name="Copy draft")).to_be_visible()
