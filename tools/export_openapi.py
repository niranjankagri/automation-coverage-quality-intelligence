"""Write the dashboard's OpenAPI document to docs/api/openapi.json.

The live server serves the same document at ``/openapi.json`` (and an interactive view at
``/docs``). The committed copy lets people read the API without running anything;
tests/unit/dashboard/test_openapi_file.py fails when it no longer matches the code.

Usage: ``python tools/export_openapi.py``
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from qualityintel.dashboard.app import create_app
from qualityintel.models.catalog import Catalog, Requirement
from qualityintel.workspace import Workspace

TARGET = Path(__file__).parents[1] / "docs" / "api" / "openapi.json"


def openapi_document() -> dict[str, Any]:
    """The OpenAPI document; it depends on the routes only, not on the loaded data."""
    placeholder = Catalog.build([Requirement(id="R-1", title="placeholder")], [])
    document: dict[str, Any] = create_app(Workspace(placeholder, [])).openapi()
    return document


def render() -> str:
    """Stable JSON text (sorted keys, trailing newline) so diffs stay small."""
    return json.dumps(openapi_document(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    """Write the file."""
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(), encoding="utf-8")
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
