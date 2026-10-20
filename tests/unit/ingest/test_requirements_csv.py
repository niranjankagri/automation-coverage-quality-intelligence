from pathlib import Path

import pytest

from qualityintel.ingest.catalog_file import catalog_from_dict, read_toml
from qualityintel.ingest.requirements_csv import (
    GENERATED_MARKER,
    MAX_FILE_BYTES,
    RequirementsCsvError,
    is_generated,
    parse_requirements_csv,
    plan_import,
    read_requirements_csv,
    render_requirements_toml,
)
from qualityintel.models.catalog import Requirement
from qualityintel.models.enums import Criticality, Priority

pytestmark = pytest.mark.unit

VALID = """id,title,description,component,priority,criticality,risk,platforms
SHOP-1,Customers can pay by card,"Visa, Mastercard; 3-D Secure",Checkout,P1,Critical,high,web;mobile-web
SHOP-2,Customers can download an invoice,,Checkout,p3,medium,,web
"""


def requirement(identifier: str, **fields: object) -> Requirement:
    """A requirement for plan tests."""
    return Requirement.model_validate({"id": identifier, "title": f"Title {identifier}", **fields})


def test_valid_file_becomes_requirements() -> None:
    """Every column maps to its field; tracker spellings (P1, Critical) are accepted."""
    parsed = parse_requirements_csv(VALID)

    assert parsed.errors == []
    assert parsed.rows == 2
    first, second = parsed.requirements
    assert first.description == "Visa, Mastercard; 3-D Secure"  # quoted commas stay inside the value
    assert first.feature == "Checkout"
    assert (first.priority, first.criticality) == (Priority.P1, Criticality.CRITICAL)
    assert first.platforms == ("web", "mobile-web")
    assert (second.description, second.risk) == (None, None)  # empty cells are "not given"


def test_column_names_are_case_insensitive_and_feature_is_an_alias() -> None:
    """'ID', 'Title', 'Feature' work as well as the documented names."""
    parsed = parse_requirements_csv("ID,Title,Feature\nR-1,Something,Search\n")

    assert parsed.requirements[0].feature == "Search"


def test_bad_rows_are_reported_with_row_and_column() -> None:
    """Spreadsheet line numbers (header = 1), the column and the reason; good rows still parse."""
    text = (
        "id,title,criticality,priority\n"
        "R-1,Fine,high,p1\n"
        "R-2,,high,p1\n"
        "R 3,Bad id,high,p1\n"
        "R-4,Bad criticality,urgent,p1\n"
        "R-5,Too,many,values,here\n"
        "R-1,Duplicate,low,p2\n"
    )

    parsed = parse_requirements_csv(text, "export.csv")

    assert [r.id for r in parsed.requirements] == ["R-1"]
    messages = [str(e) for e in parsed.errors]
    assert messages[0] == "row 3, title: is required"
    assert messages[1].startswith("row 4, id: String should match pattern")
    assert messages[2].startswith("row 5, criticality: Input should be 'critical', 'high', 'medium' or 'low'")
    assert messages[3] == "row 6: has 5 values, the header has 4 columns"
    assert messages[4] == "row 7, id: R-1 is already used in row 2"


def test_blank_lines_are_ignored() -> None:
    """Trailing or separating empty lines from spreadsheets do not count as rows."""
    parsed = parse_requirements_csv("id,title\n\nR-1,One\n,\n\nR-2,Two\n\n")

    assert [r.id for r in parsed.requirements] == ["R-1", "R-2"]
    assert parsed.errors == []


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "file is empty"),
        ("id,title\n", "has a header but no requirement rows"),
        ("id,name\nR-1,x\n", "unknown column(s): name"),
        ("title,component\nx,y\n", "missing required column(s): id"),
        ("id,title,component,feature\nR-1,x,a,b\n", "column(s) given twice: feature"),
    ],
    ids=["empty", "header-only", "unknown-column", "missing-id", "component-and-feature"],
)
def test_unusable_files_are_rejected_as_a_whole(text: str, message: str) -> None:
    """File-level problems stop the import with the file name and the reason."""
    with pytest.raises(RequirementsCsvError) as error:
        parse_requirements_csv(text, "export.csv")

    assert str(error.value).startswith("export.csv: ")
    assert message in str(error.value)


def test_utf8_with_byte_order_mark_and_non_ascii_text(tmp_path: Path) -> None:
    """Excel's 'CSV UTF-8' (with BOM) works; umlauts and arrows survive."""
    path = tmp_path / "export.csv"
    path.write_bytes("\ufeffid,title\nR-1,Gr\u00f6\u00dfe \u203a Pr\u00fcfung\n".encode())

    parsed = read_requirements_csv(path)

    assert parsed.requirements[0].title == "Gr\u00f6\u00dfe \u203a Pr\u00fcfung"


def test_non_utf8_file_gets_a_hint(tmp_path: Path) -> None:
    """A file saved in a legacy code page is refused with what to do."""
    path = tmp_path / "export.csv"
    path.write_bytes("id,title\nR-1,Gr\xf6\xdfe\n".encode("latin-1"))

    with pytest.raises(RequirementsCsvError, match=r"is not UTF-8 text .*save it as CSV UTF-8"):
        read_requirements_csv(path)


def test_oversized_and_missing_files_are_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Size limit before reading; a missing file is an import error."""
    path = tmp_path / "big.csv"
    path.write_text("id,title\nR-1,x\n", encoding="utf-8")
    monkeypatch.setattr("qualityintel.ingest.requirements_csv.MAX_FILE_BYTES", 5)

    with pytest.raises(RequirementsCsvError, match="more than the limit of 5"):
        read_requirements_csv(path)
    with pytest.raises(RequirementsCsvError, match="cannot be read"):
        read_requirements_csv(tmp_path / "missing.csv")
    assert MAX_FILE_BYTES == 10 * 1024 * 1024


def test_plan_sorts_requirements_into_added_changed_unchanged_kept() -> None:
    """Matched by id; changed rows name the fields that differ; unmentioned ones are kept."""
    existing = [requirement("R-1"), requirement("R-2", criticality="low"), requirement("R-3")]
    incoming = [requirement("R-2", criticality="high"), requirement("R-1"), requirement("R-4")]

    plan = plan_import(incoming, existing)

    assert [r.id for r in plan.added] == ["R-4"]
    assert [(before.id, fields) for before, _, fields in plan.changed] == [("R-2", ("criticality",))]
    assert [r.id for r in plan.unchanged] == ["R-1"]
    assert [r.id for r in plan.kept] == ["R-3"]
    # existing order kept, R-2 updated in place, new ones at the end
    assert [(r.id, r.criticality) for r in plan.result] == [
        ("R-1", None),
        ("R-2", Criticality.HIGH),
        ("R-3", None),
        ("R-4", None),
    ]


def test_importing_the_same_file_twice_changes_nothing() -> None:
    """The second import finds every requirement unchanged: no duplicates, same result."""
    incoming = parse_requirements_csv(VALID).requirements
    first = plan_import(incoming, [])

    second = plan_import(incoming, first.result)

    assert len(first.added) == 2
    assert second.added == []
    assert second.changed == []
    assert second.result == first.result


def test_conflicts_with_other_catalog_files_are_reported() -> None:
    """An id that a hand-written catalog already defines would be a duplicate."""
    plan = plan_import([requirement("R-1"), requirement("R-2")], [], defined_elsewhere={"R-2"})

    assert plan.conflicts == ["R-2"]


def test_generated_toml_loads_back_to_the_same_requirements(tmp_path: Path) -> None:
    """Round trip: CSV -> TOML -> catalog gives exactly the parsed requirements."""
    requirements = parse_requirements_csv(VALID).requirements
    path = tmp_path / "requirements.toml"
    path.write_text(render_requirements_toml(requirements, "export.csv"), encoding="utf-8")

    loaded = catalog_from_dict(read_toml(path), path.name).requirements

    assert list(loaded) == requirements
    assert path.read_text(encoding="utf-8").startswith(GENERATED_MARKER)


def test_special_characters_are_escaped_in_toml(tmp_path: Path) -> None:
    """Quotes, backslashes and line breaks from descriptions keep the file valid."""
    tricky = requirement("R-1", description='Say "hi" \\ then\nnew line', platforms=['a"b'])
    path = tmp_path / "requirements.toml"
    path.write_text(render_requirements_toml([tricky], "x.csv"), encoding="utf-8")

    assert catalog_from_dict(read_toml(path)).requirements[0] == tricky


def test_hand_written_files_are_recognised(tmp_path: Path) -> None:
    """Only files with the marker (or no file yet) may be overwritten by an import."""
    generated = tmp_path / "requirements.toml"
    generated.write_text(render_requirements_toml([requirement("R-1")], "x.csv"), encoding="utf-8")
    hand_written = tmp_path / "catalog.toml"
    hand_written.write_text("# my catalog\n[[requirement]]\n", encoding="utf-8")

    assert is_generated(generated)
    assert is_generated(tmp_path / "new.toml")
    assert not is_generated(hand_written)


def test_owner_column_is_imported_and_written_after_the_feature() -> None:
    """Owner from the CSV ("Owner" works too), empty = not given; the generated TOML keeps it."""
    parsed = parse_requirements_csv(
        "id,title,component,Owner\nR-1,Pay,Checkout,Payments team\nR-2,Ship,Checkout,\n"
    )
    first, second = parsed.requirements
    rendered = render_requirements_toml(parsed.requirements, "export.csv")

    assert (first.owner, second.owner) == ("Payments team", None)
    assert 'feature = "Checkout"\nowner = "Payments team"\n' in rendered
