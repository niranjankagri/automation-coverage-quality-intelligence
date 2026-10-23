"""M12 investigation workflow in a real browser: search, needs attention, drill-down, compare, copy.

Runs on the sample results (the dashboard of the demonstration) and on the collected TaskBoard
pipelines (with collection records, as a collecting deployment has them).
"""

import os
import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

ENGINE = os.environ.get("QI_E2E_BROWSER", "chromium")
TEST_KEY = "com.enterprise.automation.tests.ui.CustomerManagementTest::adminEditsACustomer"


def test_the_header_search_finds_a_test_and_opens_its_history(page: Page) -> None:
    """Keyboard only: focus the header search, type, Enter; the result opens the test's page."""
    page.goto("/#/coverage")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    page.get_by_role("searchbox", name=re.compile("^Search tests, requirements")).focus()
    page.keyboard.type("adminEditsACustomer")
    page.keyboard.press("Enter")

    expect(page).to_have_url(re.compile(r"#/search\?q=adminEditsACustomer"))
    results = page.get_by_role("region", name=re.compile("^Tests"))
    expect(results.get_by_role("link", name=TEST_KEY)).to_be_visible()
    expect(results.locator("mark").first).to_have_text(re.compile("adminEditsACustomer", re.IGNORECASE))
    results.get_by_role("link", name=TEST_KEY).click()

    expect(page.locator("#view h1")).to_have_text(TEST_KEY)
    expect(page.get_by_role("navigation", name="Breadcrumb")).to_contain_text("Tests")


def test_search_follows_typing_keeps_the_query_in_the_address_and_explains_no_results(page: Page) -> None:
    """Debounced: the address follows the input; a reload restores it; nothing found says why."""
    page.goto("/#/search")
    box = page.get_by_label("Search for")
    expect(page.locator("#search-results")).to_contain_text("at least two characters")
    box.fill("SHOP-006")

    expect(page).to_have_url(re.compile(r"q=SHOP-006"))
    expect(
        page.get_by_role("region", name=re.compile("^Requirements")).get_by_role("link", name="SHOP-006")
    ).to_be_visible()
    page.reload()
    expect(page.get_by_label("Search for")).to_have_value("SHOP-006")
    page.get_by_label("Search for").fill("zzz-no-such-thing")
    expect(page.locator("#search-results")).to_contain_text("Nothing matches")


def test_search_highlight_maps_unicode_lowercase_expansion_to_original_text(page: Page) -> None:
    """Lowercasing U+0130 adds a code point; the highlight must still cover the original letter."""
    page.goto("/#/coverage")
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
    page.goto("/#/pipelines")
    page.locator('#filters select[name="repository"]').select_option(index=1)
    repository = page.locator('#filters select[name="repository"]').input_value()
    page.get_by_role("searchbox", name=re.compile("^Search tests, requirements")).fill("38842296207")
    page.get_by_role("searchbox", name=re.compile("^Search tests, requirements")).press("Enter")

    hit = page.get_by_role("region", name=re.compile("^Pipelines")).get_by_role("link", name="38842296207")
    expect(hit).to_have_attribute(
        "href", re.compile(f"repository={re.escape(repository).replace('/', '%2F')}")
    )
    hit.click()
    expect(page.get_by_role("note").filter(has_text="Showing pipeline")).to_contain_text("38842296207 only")
    expect(page.locator("details.pipeline")).to_have_count(1)


def test_needs_attention_lists_evidence_and_leads_to_the_records(page: Page) -> None:
    """Every finding says why and how much evidence; states filter; a finding opens its test."""
    page.goto("/#/attention")
    expect(page.get_by_role("heading", name="Needs attention")).to_be_visible()
    rows = page.locator("#view table tbody tr")
    expect(rows.first).to_be_visible()
    assert rows.count() >= 8  # 2 critical gaps, 2 confirmed slowdowns, 4 flaky candidates in the samples

    page.get_by_role("navigation", name="Finding state").get_by_role(
        "link", name=re.compile("suspected")
    ).click()
    expect(page).to_have_url(re.compile("state=suspected"))
    expect(rows).to_have_count(4)
    expect(rows.first).to_contain_text("flaky candidate")
    rows.first.get_by_role("link").first.click()
    expect(page.locator("#view h1")).to_have_class(re.compile("key"))


def test_an_incomplete_pipeline_finding_links_its_pipeline_and_github_run(collected_page: Page) -> None:
    """The cancelled TaskBoard run: open, with the reason, the pipeline here and the run on GitHub."""
    page = collected_page
    page.goto("/#/attention")
    row = page.locator("#view table tbody tr").filter(has_text="incomplete pipeline")

    expect(row).to_contain_text("artifact report-ui-firefox not found")
    expect(row.get_by_role("link", name="GitHub run")).to_have_attribute(
        "href", re.compile(r"^https://github\.com/.+/attempts/1$")
    )
    row.get_by_role("link", name=re.compile("38842296207")).click()
    expect(page.locator("details.pipeline")).to_have_count(1)
    expect(page.get_by_role("navigation", name="Breadcrumb")).to_contain_text("38842296207")


def test_the_investigation_compares_two_executions(page: Page) -> None:
    """Choose two executions of a test: outcome, build, duration, failure side by side."""
    page.goto(f"/#/test?key={TEST_KEY}")
    section = page.get_by_role("region", name="Compare two executions")
    expect(section.locator("tbody")).to_contain_text("Outcome")

    options = page.get_by_label("Execution A").locator("option")
    failed = next(i for i in range(options.count()) if options.nth(i).inner_text().endswith("failed"))
    page.get_by_label("Execution A").select_option(str(failed))
    expect(section.get_by_role("row", name=re.compile("^Outcome"))).to_contain_text("failed")
    failure_of_a = section.get_by_role("row", name=re.compile("^Failure")).locator("td").first
    expect(failure_of_a).not_to_have_text("none recorded")


@pytest.mark.skipif(ENGINE != "chromium", reason="clipboard permissions are a Chromium feature")
def test_summaries_are_copied_as_text_and_markdown(page: Page) -> None:
    """The test page and the build comparison copy the server's summary, with its limitations."""
    page.context.grant_permissions(["clipboard-read", "clipboard-write"])
    page.goto(f"/#/test?key={TEST_KEY}")
    expect(page.locator("#view h1")).to_have_text(TEST_KEY)
    page.get_by_role("button", name="Copy summary (text)").click()
    expect(page.get_by_role("button", name="Copied")).to_be_visible()
    text = page.evaluate("navigator.clipboard.readText()")
    assert text.startswith(f"Investigation: {TEST_KEY}")
    assert "Limitations:" in text
    assert "flaky candidate (suspected)" in text

    page.goto("/#/compare?framework=testng&base=f5a40d5&head=1d03232")
    expect(page.get_by_role("heading", name="Compare builds")).to_be_visible()  # not the test page's button
    page.get_by_role("button", name="Copy summary (Markdown)").click()
    expect(page.get_by_role("button", name="Copied")).to_be_visible()
    markdown = page.evaluate("navigator.clipboard.readText()")
    assert markdown.startswith("### Build comparison: f5a40d5 vs 1d03232")
    assert "**Limitations**" in markdown


def test_the_comparison_shows_count_differences_and_evidence(page: Page) -> None:
    """Count differences per outcome; builds without collection records say so instead of a link."""
    page.goto("/#/compare?framework=testng&base=f5a40d5&head=1d03232")

    expect(page.locator("#view")).to_contain_text("Result counts, comparison minus baseline")
    expect(page.locator("#view .card").first).to_contain_text("no GitHub run recorded")
