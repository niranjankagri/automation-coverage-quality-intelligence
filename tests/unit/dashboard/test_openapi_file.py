import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3] / "tools"))
import export_openapi

pytestmark = pytest.mark.unit


def test_committed_openapi_document_matches_the_code() -> None:
    """docs/api/openapi.json is regenerated whenever a route changes (python tools/export_openapi.py)."""
    committed = export_openapi.TARGET.read_text(encoding="utf-8")

    assert committed == export_openapi.render(), "run: python tools/export_openapi.py"


def test_every_route_is_documented_with_a_summary() -> None:
    """Each operation has a description taken from its docstring."""
    paths = export_openapi.openapi_document()["paths"]

    for path, operations in paths.items():
        for method, operation in operations.items():
            assert operation.get("description") or operation.get("summary"), f"{method.upper()} {path}"
