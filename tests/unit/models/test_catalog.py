import pytest
from pydantic import ValidationError

from qualityintel.models.catalog import Catalog, CatalogError, Requirement, TestCase, TraceLink
from qualityintel.models.enums import AutomationStatus, Criticality, TestType

pytestmark = pytest.mark.unit


def requirement(identifier: str, **fields: object) -> Requirement:
    """A requirement with only the fields a test cares about."""
    return Requirement.model_validate({"id": identifier, "title": f"Requirement {identifier}", **fields})


def case(identifier: str, *requirements: str, status: str = "automated", **fields: object) -> TestCase:
    """A test case; automated ones get a matching pattern unless the test sets its own."""
    data: dict[str, object] = {
        "id": identifier,
        "title": f"Test case {identifier}",
        "automation_status": status,
        "requirements": requirements,
    }
    if status == "automated":
        data["automated_by"] = (f"*{identifier}*",)
    return TestCase.model_validate({**data, **fields})


def test_build_collects_links_from_the_test_cases() -> None:
    """Each requirement id listed on a test case becomes one trace link."""
    catalog = Catalog.build(
        [requirement("REQ-1"), requirement("REQ-2")],
        [case("TC-1", "REQ-1", "REQ-2"), case("TC-2", "REQ-2", status="manual")],
    )

    assert catalog.links == (
        TraceLink(requirement_id="REQ-1", test_case_id="TC-1"),
        TraceLink(requirement_id="REQ-2", test_case_id="TC-1"),
        TraceLink(requirement_id="REQ-2", test_case_id="TC-2"),
    )
    assert catalog.warnings == ()


def test_lookups_follow_the_links_in_both_directions() -> None:
    """A requirement finds its test cases and a test case finds its requirements."""
    catalog = Catalog.build(
        [requirement("REQ-1"), requirement("REQ-2")],
        [case("TC-1", "REQ-1"), case("TC-2", "REQ-1", "REQ-2")],
    )

    assert [c.id for c in catalog.test_cases_for("REQ-1")] == ["TC-1", "TC-2"]
    assert [r.id for r in catalog.requirements_for("TC-2")] == ["REQ-1", "REQ-2"]
    assert catalog.requirement("REQ-2").title == "Requirement REQ-2"
    assert catalog.test_case("TC-1").automation_status is AutomationStatus.AUTOMATED


def test_unknown_ids_raise_key_error() -> None:
    """Lookups of ids that are not in the catalog fail instead of returning None."""
    catalog = Catalog.build([requirement("REQ-1")], [])

    with pytest.raises(KeyError):
        catalog.requirement("REQ-404")
    with pytest.raises(KeyError):
        catalog.test_case("TC-404")


def test_duplicate_link_is_counted_once_with_a_warning() -> None:
    """Listing the same requirement twice on a test case is a slip, not a second link."""
    catalog = Catalog.build([requirement("REQ-1")], [case("TC-1", "REQ-1", "REQ-1")])

    assert len(catalog.links) == 1
    assert catalog.warnings == ("test case TC-1 links requirement REQ-1 more than once",)


def test_link_to_unknown_requirement_is_rejected() -> None:
    """A typo in a requirement id would silently lose coverage, so it stops the build."""
    with pytest.raises(CatalogError, match="TC-1 links unknown requirement REQ-9"):
        Catalog.build([requirement("REQ-1")], [case("TC-1", "REQ-9")])


@pytest.mark.parametrize(
    ("requirements", "cases", "message"),
    [
        (["REQ-1", "REQ-1"], [], "duplicate requirement ids: REQ-1"),
        (["REQ-1"], ["TC-1", "TC-2", "TC-1", "TC-2"], "duplicate test case ids: TC-1, TC-2"),
    ],
)
def test_duplicate_ids_are_rejected(requirements: list[str], cases: list[str], message: str) -> None:
    """Ids must be unique, otherwise links and results become ambiguous."""
    with pytest.raises(CatalogError, match=message):
        Catalog.build([requirement(r) for r in requirements], [case(c) for c in cases])


def test_automated_case_without_patterns_gives_a_warning() -> None:
    """Allowed (the catalog may be ahead of the result files) but reported."""
    catalog = Catalog.build([requirement("REQ-1")], [case("TC-1", "REQ-1", automated_by=())])

    assert catalog.warnings == (
        "automated test case TC-1 has no automated_by patterns; "
        "its executions cannot be found in result files",
    )


@pytest.mark.parametrize("status", ["manual", "planned", "blocked"])
def test_non_automated_case_cannot_list_result_patterns(status: str) -> None:
    """A manual test cannot be implemented by an automated test: contradiction."""
    with pytest.raises(ValidationError, match=f"is {status} but lists automated_by patterns"):
        case("TC-1", status=status, automated_by=("tests::x",))


def test_optional_metadata_may_be_missing() -> None:
    """Incomplete metadata is accepted; analysis reports it as unspecified."""
    loose = requirement("REQ-1")
    manual = case("TC-1", status="manual")

    assert (loose.feature, loose.criticality, loose.priority, loose.risk) == (None, None, None, None)
    assert manual.test_type is None


def test_values_are_parsed_into_enums_and_text_is_trimmed() -> None:
    """File values become enum members; stray spaces around text are removed."""
    parsed = requirement("REQ-1", title="  Login works  ", criticality="critical")
    typed = case("TC-1", test_type="api")

    assert parsed.title == "Login works"
    assert parsed.criticality is Criticality.CRITICAL
    assert typed.test_type is TestType.API


@pytest.mark.parametrize(
    "data",
    [
        {"id": "", "title": "x"},
        {"id": "REQ 1", "title": "x"},
        {"id": "-REQ", "title": "x"},
        {"id": "REQ-1", "title": ""},
        {"id": "REQ-1", "title": "x", "criticality": "urgent"},
        {"id": "REQ-1", "title": "x", "ownr": "someone"},  # a typo of owner
    ],
    ids=["empty-id", "space-in-id", "leading-dash", "empty-title", "unknown-criticality", "unknown-field"],
)
def test_invalid_requirement_fields_are_rejected(data: dict[str, object]) -> None:
    """Bad ids, unknown values and unknown fields (typos) are errors, not silently dropped."""
    with pytest.raises(ValidationError):
        Requirement.model_validate(data)


def test_models_are_immutable() -> None:
    """A loaded catalog cannot be changed by accident during analysis."""
    loaded = requirement("REQ-1")

    with pytest.raises(ValidationError):
        loaded.title = "changed"  # type: ignore[misc]


def test_catalog_created_directly_still_checks_its_links() -> None:
    """Catalogs not made by build() (e.g. read back from JSON) are validated too."""
    with pytest.raises(ValidationError, match="REQ-1 -> TC-9 refers to an unknown id"):
        Catalog(
            requirements=(requirement("REQ-1"),),
            test_cases=(),
            links=(TraceLink(requirement_id="REQ-1", test_case_id="TC-9"),),
        )
