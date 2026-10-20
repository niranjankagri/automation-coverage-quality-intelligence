"""Requirements, test cases and the links between them.

A :class:`Catalog` is the single source of truth about *what should be tested*. Execution
results (see :mod:`qualityintel.models.results`) say *what ran*; traceability joins the two.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from qualityintel.models.enums import AutomationStatus, Criticality, Priority, Risk, TestType

# Ids appear in file names, URLs and SQL; keep them to a safe, readable alphabet
Identifier = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")]
Text = Annotated[str, Field(min_length=1, max_length=500)]


class CatalogError(ValueError):
    """The catalog contradicts itself (duplicate ids, links to unknown requirements ...)."""


class _Frozen(BaseModel):
    """Base for model types: immutable, unknown fields rejected, text trimmed."""

    model_config = ConfigDict(frozen=True, extra="forbid", str_strip_whitespace=True)


class Requirement(_Frozen):
    """Something the product must do, as agreed with the business.

    Optional fields may be missing in real catalogs; analysis groups them under
    "unspecified" instead of guessing a value.
    """

    id: Identifier
    title: Text
    feature: Text | None = None
    criticality: Criticality | None = None
    priority: Priority | None = None
    risk: Risk | None = None
    platforms: tuple[Text, ...] = ()


class TestCase(_Frozen):
    """A test case with a unique id, whatever its automation status.

    Attributes:
        requirements: Ids of the requirements this test case verifies.
        automated_by: Patterns matched against result keys (``classname::name``, shell-style
            ``*`` and ``?`` wildcards) that tell which executed tests implement this case.
            Only allowed for automated test cases.
    """

    __test__ = False  # not a pytest test class, despite the name

    id: Identifier
    title: Text
    automation_status: AutomationStatus
    test_type: TestType | None = None
    framework: Text | None = None
    platforms: tuple[Text, ...] = ()
    requirements: tuple[Identifier, ...] = ()
    automated_by: tuple[Text, ...] = ()

    @model_validator(mode="after")
    def _only_automated_cases_point_at_results(self) -> Self:
        """A manual or planned case cannot be implemented by an automated test."""
        if self.automated_by and self.automation_status is not AutomationStatus.AUTOMATED:
            raise ValueError(
                f"test case {self.id} is {self.automation_status.value} but lists automated_by patterns"
            )
        return self


class TraceLink(_Frozen):
    """One requirement-to-test-case link."""

    requirement_id: Identifier
    test_case_id: Identifier


class Catalog(_Frozen):
    """Requirements, test cases and links, checked for consistency.

    Build it with :meth:`build`, which collects the links from the test cases, removes
    duplicate links (recording a warning) and rejects contradictions.
    """

    requirements: tuple[Requirement, ...]
    test_cases: tuple[TestCase, ...]
    links: tuple[TraceLink, ...]
    warnings: tuple[str, ...] = ()

    @classmethod
    def build(cls, requirements: Iterable[Requirement], test_cases: Iterable[TestCase]) -> Catalog:
        """Create a catalog from requirements and test cases.

        Raises:
            CatalogError: Duplicate requirement or test case ids, or a link to an unknown
                requirement. These are always mistakes in the source data.
        """
        requirements = tuple(requirements)
        test_cases = tuple(test_cases)
        _reject_duplicates("requirement", (r.id for r in requirements))
        _reject_duplicates("test case", (t.id for t in test_cases))

        known = {r.id for r in requirements}
        links: list[TraceLink] = []
        warnings: list[str] = []
        for case in test_cases:
            seen: set[str] = set()
            for requirement_id in case.requirements:
                if requirement_id not in known:
                    raise CatalogError(f"test case {case.id} links unknown requirement {requirement_id}")
                if requirement_id in seen:
                    # Harmless but probably a copy-paste slip: count the link once and say so
                    warnings.append(f"test case {case.id} links requirement {requirement_id} more than once")
                    continue
                seen.add(requirement_id)
                links.append(TraceLink(requirement_id=requirement_id, test_case_id=case.id))
            if case.automation_status is AutomationStatus.AUTOMATED and not case.automated_by:
                warnings.append(
                    f"automated test case {case.id} has no automated_by patterns; "
                    "its executions cannot be found in result files"
                )
        return cls(
            requirements=requirements, test_cases=test_cases, links=tuple(links), warnings=tuple(warnings)
        )

    @model_validator(mode="after")
    def _links_point_at_known_ids(self) -> Self:
        """Also protects catalogs created without :meth:`build` (e.g. from JSON)."""
        requirement_ids = {r.id for r in self.requirements}
        case_ids = {t.id for t in self.test_cases}
        for link in self.links:
            if link.requirement_id not in requirement_ids or link.test_case_id not in case_ids:
                raise ValueError(f"link {link.requirement_id} -> {link.test_case_id} refers to an unknown id")
        return self

    def requirement(self, requirement_id: str) -> Requirement:
        """Return the requirement with this id (``KeyError`` if unknown)."""
        for requirement in self.requirements:
            if requirement.id == requirement_id:
                return requirement
        raise KeyError(requirement_id)

    def test_case(self, test_case_id: str) -> TestCase:
        """Return the test case with this id (``KeyError`` if unknown)."""
        for case in self.test_cases:
            if case.id == test_case_id:
                return case
        raise KeyError(test_case_id)

    def test_cases_for(self, requirement_id: str) -> tuple[TestCase, ...]:
        """Test cases linked to one requirement, in catalog order."""
        linked = {link.test_case_id for link in self.links if link.requirement_id == requirement_id}
        return tuple(case for case in self.test_cases if case.id in linked)

    def requirements_for(self, test_case_id: str) -> tuple[Requirement, ...]:
        """Requirements one test case is linked to, in catalog order."""
        linked = {link.requirement_id for link in self.links if link.test_case_id == test_case_id}
        return tuple(r for r in self.requirements if r.id in linked)


def _reject_duplicates(kind: str, ids: Iterable[str]) -> None:
    """Raise :class:`CatalogError` naming every id that occurs more than once."""
    duplicates = sorted(identifier for identifier, count in Counter(ids).items() if count > 1)
    if duplicates:
        raise CatalogError(f"duplicate {kind} ids: {', '.join(duplicates)}")
