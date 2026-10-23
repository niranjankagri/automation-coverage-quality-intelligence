"""Prioritised coverage gaps: criticality, then risk, then gap type, grouped by owner."""

import pytest

from qualityintel.traceability.coverage import Filters, analyse_coverage
from qualityintel.traceability.gaps import UNASSIGNED, OwnerGaps, prioritised_gaps

from .helpers import case, catalog, req

pytestmark = pytest.mark.unit


def ranked(groups: tuple[OwnerGaps, ...]) -> list[str]:
    """Requirement ids in overall rank order."""
    return [g.requirement_id for g in sorted((g for o in groups for g in o.gaps), key=lambda g: g.rank)]


def test_gaps_are_ordered_by_criticality_then_risk_then_type_then_id() -> None:
    """Critical first; within it high risk first; no tests before not automated; id last."""
    requirements = [
        req("LOW-1", criticality="low", risk="high"),
        req("CRIT-NA", criticality="critical", risk="high"),
        req("CRIT-NT", criticality="critical", risk="high"),
        req("CRIT-LOWRISK", criticality="critical", risk="low"),
        req("NONE-1"),
        req("HIGH-1", criticality="high"),
        req("COVERED", criticality="critical", risk="high"),
    ]
    cases = [case("M1", "CRIT-NA", status="manual"), case("A1", "COVERED")]
    groups = prioritised_gaps(analyse_coverage(catalog(requirements, cases)))

    assert ranked(groups) == ["CRIT-NT", "CRIT-NA", "CRIT-LOWRISK", "HIGH-1", "LOW-1", "NONE-1"]


def test_gaps_are_grouped_by_owner_with_the_most_urgent_owner_first() -> None:
    """Owners follow their most urgent gap; a requirement without owner is 'unassigned'."""
    requirements = [
        req("A-LOW", owner="team-a", criticality="low"),
        req("B-CRIT", owner="team-b", criticality="critical"),
        req("A-HIGH", owner="team-a", criticality="high"),
        req("X-MED", criticality="medium"),
    ]
    groups = prioritised_gaps(analyse_coverage(catalog(requirements, [])))

    assert [(o.owner, [g.requirement_id for g in o.gaps]) for o in groups] == [
        ("team-b", ["B-CRIT"]),
        ("team-a", ["A-HIGH", "A-LOW"]),
        (UNASSIGNED, ["X-MED"]),
    ]
    assert [g.rank for o in groups for g in o.gaps] == [1, 2, 4, 3]


def test_a_gap_says_what_its_test_cases_are() -> None:
    """Not automated: the linked cases' statuses are listed; no tests: none."""
    requirements = [req("R1", criticality="high"), req("R2", criticality="high")]
    cases = [case("P", "R1", status="planned"), case("B", "R1", status="blocked")]
    (group,) = prioritised_gaps(analyse_coverage(catalog(requirements, cases)))

    first, second = group.gaps
    assert (first.requirement_id, first.kind, first.case_statuses) == ("R2", "no tests", ())
    assert (second.requirement_id, second.kind, second.case_statuses) == (
        "R1",
        "not automated",
        ("blocked", "planned"),
    )


def test_only_requirements_in_scope_are_gaps() -> None:
    """The scope's filters apply: another owner's gap is not listed."""
    requirements = [req("A", owner="team-a"), req("B", owner="team-b")]
    groups = prioritised_gaps(
        analyse_coverage(catalog(requirements, []), Filters(owners=frozenset({"team-a"})))
    )

    assert ranked(groups) == ["A"]


def test_full_automation_has_no_gaps() -> None:
    """Every requirement has an automated case: nothing to prioritise."""
    groups = prioritised_gaps(analyse_coverage(catalog([req("R1")], [case("A", "R1")])))

    assert groups == ()
