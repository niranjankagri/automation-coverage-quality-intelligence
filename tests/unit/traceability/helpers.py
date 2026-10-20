"""Small builders shared by the traceability tests."""

from datetime import UTC, datetime
from hashlib import sha256

from qualityintel.models.catalog import Catalog, Requirement, TestCase
from qualityintel.models.enums import Outcome
from qualityintel.models.results import RunContext, TestResult, TestRun


def req(identifier: str, **fields: object) -> Requirement:
    """Requirement with a generated title."""
    return Requirement.model_validate({"id": identifier, "title": identifier, **fields})


def case(identifier: str, *requirements: str, status: str = "automated", **fields: object) -> TestCase:
    """Test case; automated cases match results named after their id unless given patterns."""
    data: dict[str, object] = {
        "id": identifier,
        "title": identifier,
        "automation_status": status,
        "requirements": requirements,
    }
    if status == "automated" and "automated_by" not in fields:
        data["automated_by"] = (f"suite::{identifier}*",)
    return TestCase.model_validate({**data, **fields})


def catalog(requirements: list[Requirement], cases: list[TestCase]) -> Catalog:
    """Catalog.build with lists."""
    return Catalog.build(requirements, cases)


def result(
    name: str, outcome: Outcome = Outcome.PASSED, classname: str = "suite", **fields: object
) -> TestResult:
    """One result; by default its key is ``suite::<name>``."""
    return TestResult.model_validate({"name": name, "classname": classname, "outcome": outcome, **fields})


def run(
    *results: TestResult,
    day: int | None = 19,
    hour: int = 9,
    source: str = "junit.xml",
    **context: str,
) -> TestRun:
    """A run on 2026-10-<day> (or undated with day=None) with a unique id."""
    started = None if day is None else datetime(2026, 10, day, hour, tzinfo=UTC)
    identity = f"{source}{started}{context}{[r.key + r.outcome for r in results]}"
    return TestRun(
        run_id=sha256(identity.encode()).hexdigest(),
        source=source,
        context=RunContext.model_validate(context),
        started_at=started,
        results=results,
    )
