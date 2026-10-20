"""The sample requirements file is exactly what the import makes of samples/requirements.csv."""

from pathlib import Path

import pytest

from qualityintel.ingest.catalog_file import requirements_in
from qualityintel.ingest.requirements_csv import plan_import, read_requirements_csv, render_requirements_toml

pytestmark = pytest.mark.integration

SAMPLES = Path(__file__).parents[2] / "samples"


def test_committed_requirements_file_matches_the_csv() -> None:
    """Regenerate: python -m qualityintel requirements import samples/requirements.csv --into samples/requirements.toml --catalog samples/catalog.toml --apply."""
    parsed = read_requirements_csv(SAMPLES / "requirements.csv")

    assert parsed.errors == []
    expected = render_requirements_toml(parsed.requirements, "requirements.csv")
    assert (SAMPLES / "requirements.toml").read_text(encoding="utf-8") == expected


def test_reimporting_the_sample_csv_changes_nothing() -> None:
    """42 rows, all unchanged against the committed file: no duplicates, nothing kept aside."""
    parsed = read_requirements_csv(SAMPLES / "requirements.csv")

    plan = plan_import(parsed.requirements, requirements_in(SAMPLES / "requirements.toml"))

    assert (len(plan.unchanged), plan.added, plan.changed, plan.kept) == (42, [], [], [])
