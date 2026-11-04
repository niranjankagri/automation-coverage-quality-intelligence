"""`qi requirements sync`: preview, apply, repeat, keep local data and rollback."""

from pathlib import Path

import pytest

from qualityintel.cli import EXIT_INPUT, EXIT_OK, EXIT_USAGE, main
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.models.catalog import Requirement

pytestmark = pytest.mark.unit

CONFIG = """
base_url = "https://jira.example.test"
jql = "project = SHOP"

[fields]
id = "key"
title = "fields.summary"
criticality = "fields.customfield_1.value"
"""
CATALOG = """
include = ["requirements.toml"]

[[test_case]]
id = "TC-1"
title = "Checkout test"
automation_status = "automated"
requirements = ["SHOP-1"]
automated_by = ["c::checkout*"]
"""


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A project whose hand-written catalog links to the generated Jira file."""
    (tmp_path / "jira.toml").write_text(CONFIG, encoding="utf-8")
    (tmp_path / "catalog.toml").write_text(CATALOG, encoding="utf-8")
    return tmp_path


def run(project: Path, *extra: str) -> int:
    """Run the Jira sync against the fixture files."""
    return main(
        [
            "requirements",
            "sync",
            str(project / "jira.toml"),
            "--into",
            str(project / "requirements.toml"),
            "--catalog",
            str(project / "catalog.toml"),
            *extra,
        ]
    )


def test_preview_writes_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The default action reports additions without making a generated file."""
    monkeypatch.setattr(
        "qualityintel.cli.fetch_requirements",
        lambda config: [
            Requirement.model_validate({"id": "SHOP-1", "title": "Checkout works", "criticality": "critical"})
        ],
    )

    assert run(project) == EXIT_OK

    output = capsys.readouterr().out
    assert "PREVIEW (nothing written; add --apply to write)" in output
    assert "new 1, changed 0, unchanged 0, kept (not in Jira results) 0" in output
    assert not (project / "requirements.toml").exists()


def test_apply_keeps_links_and_missing_optional_fields(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Jira updates its mapped data while existing optional values and test links survive."""
    monkeypatch.setattr(
        "qualityintel.cli.fetch_requirements",
        lambda config: [
            Requirement(id="SHOP-1", title="Old title", description="Keep this", owner="Payments")
        ],
    )
    assert run(project, "--apply") == EXIT_OK
    monkeypatch.setattr(
        "qualityintel.cli.fetch_requirements",
        lambda config: [Requirement(id="SHOP-1", title="New title")],
    )
    capsys.readouterr()

    assert run(project, "--apply") == EXIT_OK

    catalog = load_catalog(project / "catalog.toml")
    requirement = catalog.requirement("SHOP-1")
    assert requirement.title == "New title"
    assert requirement.description == "Keep this"
    assert requirement.owner == "Payments"
    assert [(link.requirement_id, link.test_case_id) for link in catalog.links] == [("SHOP-1", "TC-1")]
    assert "catalog.toml loads: 1 requirements, 1 links" in capsys.readouterr().out


def test_sync_is_idempotent_and_keeps_issues_missing_from_jql(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A repeated sync rewrites nothing, and an issue outside the result stays in the file."""
    monkeypatch.setattr(
        "qualityintel.cli.fetch_requirements",
        lambda config: [Requirement(id="SHOP-1", title="Checkout works")],
    )
    assert run(project, "--apply") == EXIT_OK
    first = (project / "requirements.toml").read_bytes()
    capsys.readouterr()

    assert run(project, "--apply") == EXIT_OK
    assert "unchanged 1" in capsys.readouterr().out
    assert (project / "requirements.toml").read_bytes() == first

    monkeypatch.setattr("qualityintel.cli.fetch_requirements", lambda config: [])
    capsys.readouterr()
    assert run(project, "--apply") == EXIT_OK
    assert "kept (not in Jira results)" in capsys.readouterr().out
    assert load_catalog(project / "catalog.toml").requirement("SHOP-1").title == "Checkout works"


def test_failed_search_writes_nothing(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An API error is an input failure and cannot touch the generated file."""

    def fail(config: object) -> list[Requirement]:
        from qualityintel.ingest.jira_requirements import JiraRequirementsError

        raise JiraRequirementsError("Jira search", "HTTP 429 (rate limited)")

    monkeypatch.setattr("qualityintel.cli.fetch_requirements", fail)

    assert run(project, "--apply") == EXIT_INPUT
    assert "HTTP 429" in capsys.readouterr().err
    assert not (project / "requirements.toml").exists()


def test_hand_written_file_cannot_be_overwritten(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The target guard applies to Jira sync as it does to CSV import."""
    target = project / "requirements.toml"
    target.write_text("# hand-written\n", encoding="utf-8")
    monkeypatch.setattr("qualityintel.cli.fetch_requirements", lambda config: [])

    assert run(project, "--apply") == EXIT_USAGE
    assert "refusing to overwrite a hand-written file" in capsys.readouterr().err
    assert target.read_text(encoding="utf-8") == "# hand-written\n"


def test_apply_rolls_back_if_catalog_links_would_break(
    project: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A conflict with an existing test link restores the previous generated requirements file."""
    monkeypatch.setattr(
        "qualityintel.cli.fetch_requirements",
        lambda config: [Requirement(id="SHOP-1", title="Checkout works")],
    )
    assert run(project, "--apply") == EXIT_OK
    previous = (project / "requirements.toml").read_text(encoding="utf-8")
    with (project / "catalog.toml").open("a", encoding="utf-8") as catalog:
        catalog.write('\n[[requirement]]\nid = "SHOP-1"\ntitle = "Duplicate hand-written entry"\n')
    monkeypatch.setattr(
        "qualityintel.cli.fetch_requirements",
        lambda config: [Requirement(id="SHOP-2", title="Search works")],
    )
    capsys.readouterr()

    assert run(project, "--apply") == EXIT_INPUT
    assert "catalog would no longer load" in capsys.readouterr().err
    assert (project / "requirements.toml").read_text(encoding="utf-8") == previous
