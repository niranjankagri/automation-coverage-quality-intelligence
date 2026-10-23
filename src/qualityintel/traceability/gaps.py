"""Coverage gaps in priority order, grouped by owner (docs/traceability.md, "Prioritised gaps").

A **gap** is an in-scope requirement with no linked test case (*no tests*) or with linked test
cases none of which is automated (*not automated*). Gaps are ordered by:

1. criticality: critical, high, medium, low, then unspecified;
2. risk: high, medium, low, then unspecified;
3. gap type: *no tests* before *not automated* (nothing at all is worse than a manual test);
4. requirement id.

They are grouped by **owner** (``unassigned`` when the catalog names none). Owners are ordered by
their most urgent gap, then by owner name, so the first group is where the most urgent gap is.
The order uses catalog fields only; it never guesses a criticality or an owner.
"""

from __future__ import annotations

from dataclasses import dataclass

from qualityintel.models.enums import AutomationStatus, Criticality, Risk
from qualityintel.traceability.coverage import CoverageReport

UNASSIGNED = "unassigned"
CRITICALITY_ORDER = (Criticality.CRITICAL, Criticality.HIGH, Criticality.MEDIUM, Criticality.LOW, None)
RISK_ORDER = (Risk.HIGH, Risk.MEDIUM, Risk.LOW, None)
GAP_ORDER = ("no tests", "not automated")


@dataclass(frozen=True)
class Gap:
    """One requirement without automated coverage, with what its test cases are.

    Attributes:
        rank: Position in the overall order, starting at 1.
        case_statuses: Automation status of each linked test case (``manual``, ``planned``,
            ``blocked``); empty for *no tests*.
    """

    rank: int
    requirement_id: str
    title: str
    owner: str
    criticality: str | None
    risk: str | None
    kind: str
    case_statuses: tuple[str, ...]


@dataclass(frozen=True)
class OwnerGaps:
    """An owner's gaps, most urgent first."""

    owner: str
    gaps: tuple[Gap, ...]


def prioritised_gaps(coverage: CoverageReport) -> tuple[OwnerGaps, ...]:
    """The scope's coverage gaps in the documented order, grouped by owner."""
    rows = [row for row in coverage.requirements if row.status in GAP_ORDER]
    rows.sort(
        key=lambda row: (
            CRITICALITY_ORDER.index(row.requirement.criticality),
            RISK_ORDER.index(row.requirement.risk),
            GAP_ORDER.index(row.status),
            row.requirement.id,
        )
    )
    gaps = [
        Gap(
            rank=rank,
            requirement_id=row.requirement.id,
            title=row.requirement.title,
            owner=row.requirement.owner or UNASSIGNED,
            criticality=row.requirement.criticality.value if row.requirement.criticality else None,
            risk=row.requirement.risk.value if row.requirement.risk else None,
            kind=row.status,
            case_statuses=tuple(
                sorted(
                    c.automation_status.value
                    for c in row.test_cases
                    if c.automation_status is not AutomationStatus.AUTOMATED
                )
            ),
        )
        for rank, row in enumerate(rows, start=1)
    ]
    owners: dict[str, list[Gap]] = {}
    for gap in gaps:
        owners.setdefault(gap.owner, []).append(gap)
    return tuple(
        OwnerGaps(owner, tuple(owned))
        for owner, owned in sorted(owners.items(), key=lambda item: (item[1][0].rank, item[0]))
    )
