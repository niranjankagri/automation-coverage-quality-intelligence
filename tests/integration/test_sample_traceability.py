"""Traceability on the demonstration data, checked two independent ways.

1. Against counts written by hand from samples/catalog.toml (its header lists every gap).
2. Against a second, deliberately naive implementation in this file that reads the raw TOML
   and XML with the standard library only (no qualityintel code), so a bug in the real
   implementation cannot hide behind the same bug in the expectation.
"""

import re
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from qualityintel.ingest.batch import import_results
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.models.metrics import Ratio
from qualityintel.models.results import TestRun
from qualityintel.traceability.report import FAILING, PASSING, build_report

pytestmark = pytest.mark.integration

ROOT = Path(__file__).parents[2] / "samples"
# The naive implementation reads the two files the catalog is made of: the generated
# requirements (from requirements.csv) and the hand-written test cases
RAW = {
    "requirement": tomllib.loads((ROOT / "requirements.toml").read_text(encoding="utf-8"))["requirement"],
    "test_case": tomllib.loads((ROOT / "catalog.toml").read_text(encoding="utf-8"))["test_case"],
}


@pytest.fixture(scope="module")
def runs() -> list[TestRun]:
    """All sample runs, imported once for the module."""
    batch = import_results([ROOT / "results"])
    assert batch.complete
    return batch.runs


def test_hand_counted_catalog_numbers() -> None:
    """42 requirements; 4 without tests; 6 without automation; 44 cases, 6 not automated, 1 unlinked.

    requirement coverage           = (42 - 4) / 42          = 38/42
    linked cases                   = 44 - 1 (TC-NOTES-HEALTH) = 43
    automated linked cases         = 43 - 6                  = 37   -> 37/43
    automated requirement coverage = 42 - 4 - 6              = 32   -> 32/42
    """
    report = build_report(load_catalog(ROOT / "catalog.toml"), [])
    totals = report.coverage.totals

    assert totals.requirement_coverage == Ratio(numerator=38, denominator=42)
    assert totals.automation_coverage == Ratio(numerator=37, denominator=43)
    assert totals.automated_requirement_coverage == Ratio(numerator=32, denominator=42)
    assert [r.id for r in report.coverage.requirements_without_tests] == [
        "NOTES-012",
        "SHOP-010",
        "ADMIN-010",
        "ADMIN-012",
    ]
    assert [r.id for r in report.coverage.requirements_without_automation] == [
        "NOTES-011",
        "SHOP-008",
        "SHOP-009",
        "SAUCE-008",
        "ADMIN-009",
        "ADMIN-011",
    ]
    assert [r.id for r in report.coverage.uncovered_critical] == ["SHOP-008", "ADMIN-012"]
    assert [c.id for c in report.coverage.unlinked_automated_cases] == ["TC-NOTES-HEALTH"]


def naive_coverage(
    criticality: str | None = None,
) -> tuple[tuple[int, int], tuple[int, int], tuple[int, int]]:
    """Second implementation of metrics 1-3 straight from the TOML (see module docstring)."""
    reqs = [r["id"] for r in RAW["requirement"] if criticality is None or r.get("criticality") == criticality]
    cases = RAW["test_case"]
    linked_cases = {c["id"]: c for c in cases if set(c.get("requirements", [])) & set(reqs)}
    with_tests = {rid for rid in reqs if any(rid in c.get("requirements", []) for c in cases)}
    with_auto = {
        rid
        for rid in reqs
        if any(rid in c.get("requirements", []) and c["automation_status"] == "automated" for c in cases)
    }
    automated = [c for c in linked_cases.values() if c["automation_status"] == "automated"]
    return (len(with_tests), len(reqs)), (len(automated), len(linked_cases)), (len(with_auto), len(reqs))


@pytest.mark.parametrize("criticality", [None, "critical", "high", "medium", "low"])
def test_metrics_match_a_naive_second_implementation(criticality: str | None) -> None:
    """Totals and every criticality group agree with the TOML-only calculation."""
    report = build_report(load_catalog(ROOT / "catalog.toml"), [])
    numbers = report.coverage.totals if criticality is None else report.coverage.by_criticality[criticality]

    expected = naive_coverage(criticality)
    actual = tuple(
        (r.numerator, r.denominator)
        for r in (
            numbers.requirement_coverage,
            numbers.automation_coverage,
            numbers.automated_requirement_coverage,
        )
    )
    assert actual == expected


def test_snapshot_counts_match_the_raw_xml(runs: list[TestRun]) -> None:
    """Pass rate of the snapshot equals the counts read from the newest file of each folder."""
    report = build_report(load_catalog(ROOT / "catalog.toml"), runs)

    passed = verdicts = 0
    for folder in sorted(p for p in (ROOT / "results").iterdir() if p.is_dir()):
        newest = sorted(folder.glob("*.xml"))[-1]  # names start with the date; attempt3 sorts last
        for case in ET.parse(newest).getroot().iter("testcase"):
            outcomes = {child.tag for child in case} & {"failure", "error", "skipped"}
            if "skipped" in outcomes and len(outcomes) == 1:
                continue
            verdicts += 1
            passed += not outcomes
    assert report.pass_rate == Ratio(numerator=passed, denominator=verdicts)
    assert {Path(r.source).parent.name for r in report.snapshot} == {
        p.name for p in (ROOT / "results").iterdir() if p.is_dir()
    }


def test_unmatched_results_are_the_database_self_checks(runs: list[TestRun]) -> None:
    """The only real tests no case claims are the DB layer's own framework checks."""
    report = build_report(load_catalog(ROOT / "catalog.toml"), runs)

    unmatched = sorted({e.result.name for e in report.unmatched})
    assert unmatched == [
        "assertionFailuresShowTheRow",
        "connectsAndReadsTheSchema",
        "parametersAreBoundNotConcatenated",
        "queryForOneRejectsSeveralRows",
    ]
    assert report.automated_cases_without_results == ()


def test_every_pattern_in_the_catalog_matches_at_least_one_real_test(runs: list[TestRun]) -> None:
    """A pattern that matches nothing is a typo or a renamed test; none may exist."""
    keys = {r.key for run in runs for r in run.results}
    for case in RAW["test_case"]:
        for pattern in case.get("automated_by", []):
            regex = re.compile(
                "".join(
                    ".*" if p == "*" else "." if p == "?" else re.escape(p)
                    for p in re.split(r"([*?])", pattern)
                )
            )
            assert any(regex.fullmatch(k) for k in keys), f"{case['id']}: {pattern} matches no test"


def test_the_real_failures_show_up_on_their_day(runs: list[TestRun]) -> None:
    """13 Oct: ADMIN-003 fails (Firefox timeout). 19 Oct attempt 1: SHOP-006 (critical) fails."""
    catalog = load_catalog(ROOT / "catalog.toml")

    on_13th = [r for r in runs if r.source.endswith("2026-10-13_f5a40d5_38374469545.xml")]
    first_attempt = [r for r in runs if r.source.endswith("39229363499-attempt1.xml")]

    report_13 = build_report(catalog, on_13th)
    assert report_13.requirement_status["ADMIN-003"] == FAILING
    assert report_13.requirement_status["ADMIN-004"] == PASSING
    assert report_13.failing_critical == ()

    report_attempt1 = build_report(catalog, first_attempt)
    assert report_attempt1.requirement_status["SHOP-006"] == FAILING
    assert report_attempt1.failing_critical == ("SHOP-006",)
