"""Layout regression tests: geometry, not pixels (docs/dashboard.md).

Pixel comparisons differ between operating systems and font versions (the project is developed on
Windows and tested on Linux), so they would fail on noise. These tests check what a broken
layout looks like instead, at phone, tablet and desktop widths: page regions overlapping, content
wider than the window, card values spilling out of their cards, navigation links pushed off the
screen.
"""

from itertools import pairwise
from typing import Any

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e

WIDTHS = [390, 768, 1280]
PAGES = [
    "#/",
    "#/requirements",
    "#/requirement/SHOP-006",
    "#/tests",
    "#/test?key=com.enterprise.automation.tests.ui.CustomerManagementTest%3A%3AadminEditsACustomer",
    "#/runs",
    "#/stability",
    "#/trends",
    "#/compare?framework=testng&base=f5a40d5&head=1d03232",
    "#/pipelines",
    "#/collection",
    "#/attention",
    "#/search?q=checkout",
]
REGIONS = ["header.top", "#filters", ".databar", "#catalog-notice", "main"]


def boxes(page: Page) -> list[dict[str, Any]]:
    """Bounding boxes of the visible page regions, top to bottom."""
    found: list[dict[str, Any]] = []
    for selector in REGIONS:
        box = (
            page.locator(selector).first.bounding_box() if page.locator(selector).first.is_visible() else None
        )
        if box:
            found.append({"name": selector, **box})
    return found


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("route", PAGES)
def test_page_regions_stack_without_overlapping_or_spilling(page: Page, route: str, width: int) -> None:
    """Header, filters, data bar, notice and content follow each other, inside the window."""
    page.set_viewport_size({"width": width, "height": 900})
    page.goto(f"/{route}")
    expect(page.locator("#view h1")).to_be_visible()
    page.wait_for_load_state("networkidle")

    regions = boxes(page)
    for upper, lower in pairwise(regions):
        assert upper["y"] + upper["height"] <= lower["y"] + 1, f"{upper['name']} overlaps {lower['name']}"
    for region in regions:
        assert region["x"] >= 0, f"{region['name']} starts left of the window"
        assert region["x"] + region["width"] <= width + 1, f"{region['name']} spills right"
    document_width = page.evaluate("document.documentElement.scrollWidth")
    overflow = page.evaluate(
        """width => [...document.querySelectorAll('body *')]
          .map(e => ({element: `${e.tagName.toLowerCase()}${e.id ? `#${e.id}` : ''}`,
            className: typeof e.className === 'string' ? e.className : '',
            right: Math.ceil(e.getBoundingClientRect().right), text: (e.textContent || '').slice(0, 80)}))
          .filter(e => e.right > width + 1).slice(0, 12)""",
        width,
    )
    assert document_width <= width + 1, f"{route} has page-wide horizontal overflow at {width}px: {overflow}"


@pytest.mark.parametrize("width", WIDTHS)
def test_card_values_fit_their_cards_and_nav_links_stay_on_screen(page: Page, width: int) -> None:
    """Numbers like '90.5 %' never overflow a card; every section link can be reached."""
    page.set_viewport_size({"width": width, "height": 900})
    page.goto("/")
    expect(page.get_by_role("heading", name="Overview", exact=True)).to_be_visible()
    if width <= 720:
        page.locator(".mobile-nav > summary").click()

    overflowing = page.evaluate(
        "[...document.querySelectorAll('.card .value')].filter(e => e.scrollWidth > e.clientWidth + 1)"
        ".map(e => e.textContent)"
    )
    assert overflowing == []
    for link in page.locator("nav[aria-label=Sections] a").all():
        link.scroll_into_view_if_needed()
        box = link.bounding_box()
        assert box is not None
        assert box["x"] >= 0, link.inner_text()
        assert box["x"] + box["width"] <= width + 1, link.inner_text()
