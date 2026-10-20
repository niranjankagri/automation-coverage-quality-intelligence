"""Coverage metrics against hand-calculated values (docs/metrics.md sections 1-3)."""

import pytest

from qualityintel.models.catalog import Catalog
from qualityintel.models.metrics import Ratio
from qualityintel.traceability.coverage import UNSPECIFIED, Filters, analyse_coverage

from .helpers import case, catalog, req

pytestmark = pytest.mark.unit


def ratio(numerator: int, denominator: int) -> Ratio:
    """Short form for expected values."""
    return Ratio(numerator=numerator, denominator=denominator)


@pytest.fixture
def shop() -> Catalog:
    """Five requirements, six test cases.

    R1 critical: TC-1 automated, TC-2 manual          -> covered, automated
    R2 critical: TC-3 planned                          -> covered, not automated
    R3 high:     TC-4 automated (also linked to R4)    -> covered, automated
    R4 medium:   TC-4 automated                        -> covered, automated
    R5 low:      nothing                               -> no tests
    TC-5 automated, linked to nothing                  -> unlinked
    """
    return catalog(
        [
            req("R1", feature="Checkout", criticality="critical", platforms=["web"]),
            req("R2", feature="Checkout", criticality="critical", platforms=["web", "api"]),
            req("R3", feature="Search", criticality="high", platforms=["api"]),
            req("R4", feature="Search", criticality="medium"),
            req("R5", criticality="low"),
        ],
        [
            case("TC-1", "R1", test_type="ui", framework="playwright"),
            case("TC-2", "R1", status="manual", test_type="ui"),
            case("TC-3", "R2", status="planned", test_type="api"),
            case("TC-4", "R3", "R4", test_type="api", framework="pytest"),
            case("TC-5", test_type="api"),
        ],
    )


def test_totals(shop: Catalog) -> None:
    """Requirement coverage 4/5; automation 2 of 4 linked cases; automated requirements 3/5.

    Linked cases are TC-1..TC-4 (TC-4 counts once although it has two links); automated among
    them: TC-1 and TC-4. Unlinked TC-5 stays out of the denominator.
    """
    totals = analyse_coverage(shop).totals

    assert totals.requirement_coverage == ratio(4, 5)
    assert totals.automation_coverage == ratio(2, 4)
    assert totals.automated_requirement_coverage == ratio(3, 5)


def test_gaps(shop: Catalog) -> None:
    """Each gap list contains exactly the requirements or cases the definition describes."""
    report = analyse_coverage(shop)

    assert [r.id for r in report.requirements_without_tests] == ["R5"]
    assert [r.id for r in report.requirements_without_automation] == ["R2"]
    assert [r.id for r in report.uncovered_critical] == ["R2"]
    assert [c.id for c in report.unlinked_automated_cases] == ["TC-5"]
    assert [r.status for r in report.requirements] == [
        "automated",
        "not automated",
        "automated",
        "automated",
        "no tests",
    ]


def test_breakdown_by_feature_and_criticality(shop: Catalog) -> None:
    """Missing feature goes to 'unspecified'; every group has its own denominators."""
    report = analyse_coverage(shop)

    assert report.by_feature["Checkout"].automated_requirement_coverage == ratio(1, 2)
    assert report.by_feature["Search"].automation_coverage == ratio(1, 1)  # TC-4 once
    assert report.by_feature[UNSPECIFIED].requirement_coverage == ratio(0, 1)
    assert report.by_criticality["critical"].automated_requirement_coverage == ratio(1, 2)
    assert set(report.by_criticality) == {"critical", "high", "medium", "low"}


def test_breakdown_by_platform_counts_a_requirement_in_each_of_its_platforms(shop: Catalog) -> None:
    """R2 is web and api; R4 and R5 have no platform."""
    by_platform = analyse_coverage(shop).by_platform

    assert by_platform["web"].requirement_coverage == ratio(2, 2)
    assert by_platform["api"].requirement_coverage == ratio(2, 2)
    assert by_platform[UNSPECIFIED].requirement_coverage == ratio(1, 2)


def test_breakdown_by_test_type_keeps_all_requirements_in_the_denominator(shop: Catalog) -> None:
    """UI cases reach R1 only (1/5); API cases reach R2, R3, R4 (3/5), two of them automated."""
    by_type = analyse_coverage(shop).by_test_type

    assert by_type["ui"].requirement_coverage == ratio(1, 5)
    assert by_type["ui"].automation_coverage == ratio(1, 2)
    assert by_type["api"].requirement_coverage == ratio(3, 5)
    assert by_type["api"].automated_requirement_coverage == ratio(2, 5)
    assert by_type["api"].automation_coverage == ratio(1, 2)  # TC-3 planned, TC-4 automated


def test_requirement_filters_change_the_scope(shop: Catalog) -> None:
    """Only critical requirements: 2 in scope, both covered, one automated."""
    report = analyse_coverage(shop, Filters(criticalities=frozenset({"critical"})))

    assert report.totals.requirement_coverage == ratio(2, 2)
    assert report.totals.automated_requirement_coverage == ratio(1, 2)
    assert [r.requirement.id for r in report.requirements] == ["R1", "R2"]


def test_test_case_filters_hide_other_cases(shop: Catalog) -> None:
    """Framework pytest: only TC-4 counts, so R1 and R2 have no tests in this scope."""
    report = analyse_coverage(shop, Filters(frameworks=frozenset({"pytest"})))

    assert report.totals.requirement_coverage == ratio(2, 5)
    assert [r.id for r in report.requirements_without_tests] == ["R1", "R2", "R5"]
    assert report.unlinked_automated_cases == ()  # TC-5 has no framework


def test_filter_on_unspecified_metadata(shop: Catalog) -> None:
    """'unspecified' is a value you can filter on to find incomplete records."""
    report = analyse_coverage(shop, Filters(features=frozenset({UNSPECIFIED})))

    assert [r.requirement.id for r in report.requirements] == ["R5"]


def test_nothing_in_scope_gives_not_applicable_not_zero() -> None:
    """A filter that matches no requirement: every metric is n/a (0/0)."""
    report = analyse_coverage(
        catalog([req("R1", criticality="low")], []), Filters(criticalities=frozenset({"critical"}))
    )

    assert report.totals.requirement_coverage.value is None
    assert report.totals.automation_coverage.value is None
    assert report.totals.automated_requirement_coverage.value is None
    assert report.by_feature == {}


def test_requirements_without_any_case_give_na_automation_coverage() -> None:
    """No linked case at all: automation coverage has nothing to divide by."""
    totals = analyse_coverage(catalog([req("R1"), req("R2")], [])).totals

    assert totals.requirement_coverage == ratio(0, 2)
    assert totals.automation_coverage.value is None


def test_duplicate_mapping_counts_once() -> None:
    """A test case listing the same requirement twice is one link, so 1/1, not 2/1."""
    totals = analyse_coverage(catalog([req("R1")], [case("TC-1", "R1", "R1")])).totals

    assert totals.automation_coverage == ratio(1, 1)
    assert totals.requirement_coverage == ratio(1, 1)


def test_incomplete_metadata_is_grouped_not_dropped() -> None:
    """Requirements and cases without metadata still count, under 'unspecified'."""
    report = analyse_coverage(catalog([req("R1")], [case("TC-1", "R1")]))

    assert report.totals.requirement_coverage == ratio(1, 1)
    assert set(report.by_feature) == set(report.by_criticality) == set(report.by_platform) == {UNSPECIFIED}
    assert set(report.by_test_type) == {UNSPECIFIED}
