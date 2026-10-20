"""Coverage metrics, gaps and breakdowns computed from the catalog alone.

Formulas and denominators are defined in docs/metrics.md; each function here names the
section it implements. Nothing in this module looks at execution results: coverage says what
is *designed and automated*, pass rate (see :mod:`qualityintel.traceability.report`) says what
*worked in the analysed runs*.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from qualityintel.models.catalog import Catalog, Requirement, TestCase
from qualityintel.models.enums import AutomationStatus, Criticality
from qualityintel.models.metrics import Ratio

UNSPECIFIED = "unspecified"


@dataclass(frozen=True)
class Filters:
    """Scope of an analysis; ``None`` or empty = no restriction on that dimension.

    Requirement filters (feature, owner, criticality, platform) choose the requirements in scope.
    Test case filters (test type, framework) choose which linked test cases count; a
    requirement whose linked cases are all filtered out counts as having no tests *in this
    scope*.
    """

    features: frozenset[str] = frozenset()
    owners: frozenset[str] = frozenset()
    criticalities: frozenset[str] = frozenset()
    platforms: frozenset[str] = frozenset()
    test_types: frozenset[str] = frozenset()
    frameworks: frozenset[str] = frozenset()

    def keeps_requirement(self, requirement: Requirement) -> bool:
        """True when the requirement is in scope."""
        return (
            _allowed(self.features, [requirement.feature or UNSPECIFIED])
            and _allowed(self.owners, [requirement.owner or UNSPECIFIED])
            and _allowed(self.criticalities, [_value(requirement.criticality)])
            and _allowed(self.platforms, list(requirement.platforms) or [UNSPECIFIED])
        )

    def keeps_test_case(self, case: TestCase) -> bool:
        """True when the test case counts in this scope."""
        return _allowed(self.test_types, [_value(case.test_type)]) and _allowed(
            self.frameworks, [case.framework or UNSPECIFIED]
        )


@dataclass(frozen=True)
class CoverageNumbers:
    """The three catalog metrics for one scope (docs/metrics.md, sections 1-3)."""

    requirement_coverage: Ratio
    automation_coverage: Ratio
    automated_requirement_coverage: Ratio


@dataclass(frozen=True)
class RequirementCoverage:
    """One requirement with the linked test cases that count in the scope."""

    requirement: Requirement
    test_cases: tuple[TestCase, ...]

    @property
    def automated_cases(self) -> tuple[TestCase, ...]:
        """Linked cases with status ``automated``."""
        return tuple(c for c in self.test_cases if c.automation_status is AutomationStatus.AUTOMATED)

    @property
    def status(self) -> str:
        """``no tests``, ``not automated`` or ``automated``."""
        if not self.test_cases:
            return "no tests"
        return "automated" if self.automated_cases else "not automated"


@dataclass(frozen=True)
class CoverageReport:
    """Everything the catalog says about coverage within one scope."""

    filters: Filters
    totals: CoverageNumbers
    requirements: tuple[RequirementCoverage, ...]
    unlinked_automated_cases: tuple[TestCase, ...]
    by_feature: dict[str, CoverageNumbers] = field(default_factory=dict)
    by_criticality: dict[str, CoverageNumbers] = field(default_factory=dict)
    by_platform: dict[str, CoverageNumbers] = field(default_factory=dict)
    by_test_type: dict[str, CoverageNumbers] = field(default_factory=dict)

    @property
    def requirements_without_tests(self) -> tuple[Requirement, ...]:
        """Gap: in-scope requirements with no linked test case."""
        return tuple(r.requirement for r in self.requirements if r.status == "no tests")

    @property
    def requirements_without_automation(self) -> tuple[Requirement, ...]:
        """Gap: requirements with linked test cases, none of them automated."""
        return tuple(r.requirement for r in self.requirements if r.status == "not automated")

    @property
    def uncovered_critical(self) -> tuple[Requirement, ...]:
        """Gap: critical requirements without any automated linked test case."""
        return tuple(
            r.requirement
            for r in self.requirements
            if r.requirement.criticality is Criticality.CRITICAL and not r.automated_cases
        )


def analyse_coverage(catalog: Catalog, filters: Filters | None = None) -> CoverageReport:
    """Compute totals, per-requirement status, gaps and breakdowns for one scope."""
    scope = filters or Filters()
    rows = _rows(catalog, scope)
    linked = {link.test_case_id for link in catalog.links}
    unlinked = tuple(
        case
        for case in catalog.test_cases
        if case.automation_status is AutomationStatus.AUTOMATED
        and case.id not in linked
        and scope.keeps_test_case(case)
    )
    return CoverageReport(
        filters=scope,
        totals=coverage_numbers(rows),
        requirements=rows,
        unlinked_automated_cases=unlinked,
        by_feature=_group(rows, lambda r: [r.requirement.feature or UNSPECIFIED]),
        by_criticality=_group(rows, lambda r: [_value(r.requirement.criticality)]),
        by_platform=_group(rows, lambda r: list(r.requirement.platforms) or [UNSPECIFIED]),
        by_test_type=_by_test_type(rows),
    )


def coverage_numbers(rows: Iterable[RequirementCoverage]) -> CoverageNumbers:
    """The three metrics for a set of requirement rows.

    - Requirement coverage (docs/metrics.md section 1): rows with >= 1 linked case / rows.
    - Automation coverage (section 2): distinct linked cases that are automated / distinct
      linked cases. A case linked to several requirements counts once.
    - Automated requirement coverage (section 3): rows with >= 1 automated case / rows.
    """
    rows = tuple(rows)
    cases = {case.id: case for row in rows for case in row.test_cases}
    automated = [c for c in cases.values() if c.automation_status is AutomationStatus.AUTOMATED]
    return CoverageNumbers(
        requirement_coverage=Ratio(numerator=sum(1 for r in rows if r.test_cases), denominator=len(rows)),
        automation_coverage=Ratio(numerator=len(automated), denominator=len(cases)),
        automated_requirement_coverage=Ratio(
            numerator=sum(1 for r in rows if r.automated_cases), denominator=len(rows)
        ),
    )


def _rows(catalog: Catalog, scope: Filters) -> tuple[RequirementCoverage, ...]:
    """One row per in-scope requirement with the linked cases that count in the scope."""
    return tuple(
        RequirementCoverage(
            requirement=requirement,
            test_cases=tuple(c for c in catalog.test_cases_for(requirement.id) if scope.keeps_test_case(c)),
        )
        for requirement in catalog.requirements
        if scope.keeps_requirement(requirement)
    )


def _group(
    rows: tuple[RequirementCoverage, ...], keys: Callable[[RequirementCoverage], list[str]]
) -> dict[str, CoverageNumbers]:
    """Metrics per group of requirements; a requirement with several keys is in each group."""
    groups: dict[str, list[RequirementCoverage]] = {}
    for row in rows:
        for key in keys(row):
            groups.setdefault(key, []).append(row)
    return {key: coverage_numbers(groups[key]) for key in sorted(groups)}


def _by_test_type(rows: tuple[RequirementCoverage, ...]) -> dict[str, CoverageNumbers]:
    """Metrics per test type: same requirements, only the linked cases of that type.

    The requirement denominator stays every in-scope requirement, so "api: 70 %" reads as
    "API tests reach 70 % of the requirements". Rows can add up to more than the total.
    """
    types = sorted({_value(c.test_type) for row in rows for c in row.test_cases})
    return {
        test_type: coverage_numbers(
            RequirementCoverage(
                requirement=row.requirement,
                test_cases=tuple(c for c in row.test_cases if _value(c.test_type) == test_type),
            )
            for row in rows
        )
        for test_type in types
    }


def _allowed(chosen: frozenset[str], values: list[str]) -> bool:
    """No restriction, or at least one of the item's values was chosen."""
    return not chosen or any(value in chosen for value in values)


def _value(member: object) -> str:
    """Enum value as text, ``unspecified`` for missing metadata."""
    return UNSPECIFIED if member is None else str(getattr(member, "value", member))
