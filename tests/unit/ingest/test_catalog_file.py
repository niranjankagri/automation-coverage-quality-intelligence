from pathlib import Path

import pytest

from qualityintel.ingest.catalog_file import CatalogFileError, load_catalog
from qualityintel.ingest.errors import IngestError

pytestmark = pytest.mark.unit

VALID = """
[[requirement]]
id = "R-1"
title = "Checkout works"
criticality = "critical"

[[requirement]]
id = "R-2"
title = "Search works"

[[test_case]]
id = "TC-1"
title = "Checkout happy path"
automation_status = "automated"
test_type = "ui"
requirements = ["R-1"]
automated_by = ["ui/checkout.spec.ts::*"]

[[test_case]]
id = "TC-2"
title = "Search by hand"
automation_status = "manual"
requirements = ["R-2", "R-2"]
"""


def test_valid_catalog_loads_with_links_and_warnings(tmp_path: Path) -> None:
    """Entries become models; the duplicate link is counted once with a warning."""
    catalog = load_catalog(_write(tmp_path, VALID))

    assert [r.id for r in catalog.requirements] == ["R-1", "R-2"]
    assert [(link.requirement_id, link.test_case_id) for link in catalog.links] == [
        ("R-1", "TC-1"),
        ("R-2", "TC-2"),
    ]
    assert catalog.warnings == ("test case TC-2 links requirement R-2 more than once",)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("[[requirement]]\nid = ", r"not valid TOML"),
        ("[[requirements]]\nid = 'R'\ntitle = 't'", r"unknown section\(s\): requirements"),
        ("", r"contains no \[\[requirement\]\] entries"),
        ("requirement = 'x'", r"requirement must be an array of tables"),
        (
            "[[requirement]]\nid = 'R-1'\ntitle = 't'\ncriticality = 'urgent'",
            r"requirement\[1\] \(R-1\)\.criticality: Input should be 'critical', 'high', 'medium' or 'low'",
        ),
        (
            VALID + "\n[[test_case]]\nid = 'TC-3'\ntitle = 't'\nautomation_status = 'automatic'",
            r"test_case\[3\] \(TC-3\)\.automation_status",
        ),
        ("[[requirement]]\ntitle = 'no id'", r"requirement\[1\]\.id: Field required"),
        (VALID + "\n[[requirement]]\nid = 'R-1'\ntitle = 'again'", r"duplicate requirement ids: R-1"),
        (
            VALID.replace('requirements = ["R-1"]', 'requirements = ["R-9"]'),
            r"TC-1 links unknown requirement R-9",
        ),
    ],
    ids=[
        "toml-syntax",
        "unknown-section",
        "empty",
        "not-a-table-array",
        "bad-enum",
        "bad-status",
        "missing-id",
        "duplicate",
        "unknown-link",
    ],
)
def test_problems_name_the_file_and_the_entry(tmp_path: Path, text: str, message: str) -> None:
    """Each error says which file and which entry/field is wrong."""
    with pytest.raises(CatalogFileError, match=rf"^catalog\.toml: .*{message}"):
        load_catalog(_write(tmp_path, text))


def test_unreadable_file_is_a_catalog_error(tmp_path: Path) -> None:
    """A missing file gives an import error (exit code 3 in the CLI), not a traceback."""
    with pytest.raises(CatalogFileError, match=r"^missing\.toml: cannot be read"):
        load_catalog(tmp_path / "missing.toml")


def test_catalog_errors_are_ingest_errors() -> None:
    """Callers handle catalog and result problems the same way."""
    assert issubclass(CatalogFileError, IngestError)


def _write(tmp_path: Path, text: str) -> Path:
    """Write text to catalog.toml and return the path."""
    path = tmp_path / "catalog.toml"
    path.write_text(text, encoding="utf-8")
    return path


REQUIREMENTS_ONLY = """
[[requirement]]
id = "R-9"
title = "Imported requirement"
criticality = "high"
"""


def test_include_adds_the_entries_of_another_file(tmp_path: Path) -> None:
    """A generated requirements file next to hand-written test cases forms one catalog."""
    (tmp_path / "requirements.toml").write_text(REQUIREMENTS_ONLY, encoding="utf-8")
    main = 'include = ["requirements.toml"]\n' + VALID.replace(
        'requirements = ["R-2", "R-2"]', 'requirements = ["R-9"]'
    )

    catalog = load_catalog(_write(tmp_path, main))

    assert [r.id for r in catalog.requirements] == ["R-1", "R-2", "R-9"]
    assert ("R-9", "TC-2") in [(link.requirement_id, link.test_case_id) for link in catalog.links]


def test_catalog_made_only_of_includes(tmp_path: Path) -> None:
    """The main file may hold test cases only; requirements come from the include."""
    (tmp_path / "requirements.toml").write_text(REQUIREMENTS_ONLY, encoding="utf-8")

    catalog = load_catalog(_write(tmp_path, 'include = ["requirements.toml"]\n'))

    assert [r.id for r in catalog.requirements] == ["R-9"]


@pytest.mark.parametrize(
    ("include", "included", "message"),
    [
        ('include = "requirements.toml"', None, r"include must be a list of file names"),
        ('include = ["missing.toml"]', None, r"^missing\.toml: cannot be read"),
        ('include = ["../outside.toml"]', None, r"must be a file name or a path inside"),
        (
            'include = ["requirements.toml"]',
            'include = ["more.toml"]\n' + REQUIREMENTS_ONLY,
            r"cannot include further files",
        ),
        (
            'include = ["requirements.toml"]',
            REQUIREMENTS_ONLY.replace("R-9", "R-1"),
            r"requirement R-1 is also defined in catalog\.toml",
        ),
        ('include = ["requirements.toml"]', "[[requirement]]\nid = ", r"^requirements\.toml: not valid TOML"),
    ],
    ids=["not-a-list", "missing", "outside-folder", "nested", "duplicate-across-files", "broken-include"],
)
def test_bad_includes_are_reported(tmp_path: Path, include: str, included: str | None, message: str) -> None:
    """Every include problem names the file that has it."""
    if included is not None:
        (tmp_path / "requirements.toml").write_text(included, encoding="utf-8")

    with pytest.raises(CatalogFileError, match=message):
        load_catalog(_write(tmp_path, include + "\n" + VALID))


def test_a_catalog_can_say_what_it_is(tmp_path: Path) -> None:
    """notice: kept trimmed on the catalog; a wrong type or an empty text is refused."""
    good = tmp_path / "good.toml"
    good.write_text(
        'notice = " Synthetic requirements "\n[[requirement]]\nid = "R-1"\ntitle = "T"\n', encoding="utf-8"
    )
    bad = tmp_path / "bad.toml"
    bad.write_text('notice = 3\n[[requirement]]\nid = "R-1"\ntitle = "T"\n', encoding="utf-8")

    assert load_catalog(good).notice == "Synthetic requirements"
    with pytest.raises(CatalogFileError, match="notice"):
        load_catalog(bad)
