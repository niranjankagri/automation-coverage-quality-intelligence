"""Browser smoke test of a deployed report: python tools/report_smoke.py URL.

After a deployment (docs/deployment.md), opens the report (``/next/``) in headless Chromium the way a
visitor would: every section shows its own heading; choosing a repository narrows the report; a
test opens its own execution (same run as the row clicked); a requirement opens inside the report;
and no page logs an application error. Exit code 0 when every check passed, 1 otherwise; one line
per check. Needs ``pip install -e ".[e2e]"`` and ``playwright install chromium``.
"""

from __future__ import annotations

import argparse
import re
import sys
from urllib.parse import parse_qs

from playwright.sync_api import Error, Page, sync_playwright

SECTIONS = {
    "overview": "Overview",
    "results": "Test Results",
    "failures": "Failures & Stability",
    "trends": "Trends",
    "coverage": "Coverage & Requirements",
}
TIMEOUT_MS = 60_000


def section(page: Page, base: str, route: str, title: str) -> None:
    """Open ``route`` and wait for its own heading (not the skeleton) and its data.

    Waits use locators: the page's Content Security Policy forbids evaluating strings as script.
    """
    page.goto(f"{base}/next/#/{route}")
    page.locator("main h1", has_text=title).first.wait_for(timeout=TIMEOUT_MS)
    page.locator("main[aria-busy]").wait_for(state="detached", timeout=TIMEOUT_MS)


def checks(page: Page, base: str) -> list[tuple[str, bool, str]]:
    """Every check as (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []
    for route, title in SECTIONS.items():
        section(page, base, route, title)
        results.append((f"section {title}", page.locator(".error-box").count() == 0, route))

    section(page, base, "overview", "Overview")
    choices = page.locator("#filter-repository option").evaluate_all(
        "els => els.map(e => e.value).filter(Boolean)"
    )
    if choices:
        page.locator("#filter-repository").select_option(choices[0])
        page.wait_for_url(re.compile(r"repository="), timeout=TIMEOUT_MS)
        page.locator("main[aria-busy]").wait_for(state="detached", timeout=TIMEOUT_MS)
        eyebrow = page.locator("main .eyebrow").first.inner_text()
        results.append(
            ("repository selection", choices[0].split("/")[-1].upper() in eyebrow.upper(), choices[0])
        )
    else:
        results.append(("repository selection", False, "no repository to choose"))

    section(page, base, "results?status=passed", "Test Results")
    row = page.locator(".test-row").first
    if row.count():
        clicked = parse_qs(row.get_attribute("href").split("?", 1)[1])["run"][0]  # type: ignore[union-attr]
        row.click()
        page.locator(".test-title").wait_for(timeout=TIMEOUT_MS)
        shown = page.locator(".tab-panel a[href^='/#/run/']").first.get_attribute("href") or ""
        results.append(("test drill-down opens its own execution", clicked[:12] in shown, clicked[:12]))
    else:
        results.append(("test drill-down opens its own execution", False, "no passed results listed"))

    section(page, base, "coverage", "Coverage & Requirements")
    page.locator(".coverage-tree > .node > summary").first.click()
    page.locator(".coverage-tree .node .node > summary").first.click()
    link = page.locator(".req-row a").first
    requirement = link.inner_text()
    link.click()
    page.locator("main h1", has_text=requirement).wait_for(timeout=TIMEOUT_MS)
    results.append(("coverage drill-down opens a requirement", "#/requirement?" in page.url, requirement))
    return results


def main(argv: list[str] | None = None) -> int:
    """Run the checks in Chromium and print one line per check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="base address, e.g. https://quality-intelligence.onrender.com")
    args = parser.parse_args(argv)
    base = args.url.rstrip("/")
    errors: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
        try:
            results = checks(page, base)
        except Error as error:
            print(f"FAIL  the report cannot be checked: {error.message.splitlines()[0]}")
            return 1
        finally:
            browser.close()
    results.append(("no application errors", not errors, "; ".join(errors)[:300]))
    for name, passed, detail in results:
        print(f"{'ok  ' if passed else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
