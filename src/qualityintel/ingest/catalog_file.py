"""Read a requirement catalog from a TOML file.

TOML because Python reads it without extra dependencies (``tomllib``) and it is easy to edit
and review in pull requests. Layout (see samples/catalog.toml)::

    [[requirement]]
    id = "SHOP-006"
    title = "Customers can check out and place an order"
    feature = "Toolshop / Checkout"
    criticality = "critical"
    platforms = ["web"]

    [[test_case]]
    id = "TC-SHOP-006"
    title = "Checkout as guest and as logged-in customer"
    automation_status = "automated"
    test_type = "ui"
    requirements = ["SHOP-006"]
    automated_by = ["ui/checkout.spec.ts::*"]

Every problem is reported with its place in the file (``test_case[3].automation_status``),
so a typo in a large catalog is quick to find.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from qualityintel.ingest.errors import IngestError
from qualityintel.models.catalog import Catalog, CatalogError, Requirement, TestCase

TOP_LEVEL_KEYS = frozenset({"requirement", "test_case"})


class CatalogFileError(IngestError):
    """The catalog file cannot be read or contradicts itself."""


def load_catalog(path: Path) -> Catalog:
    """Load and validate a catalog file.

    Raises:
        CatalogFileError: Unreadable file, TOML syntax error, unknown sections, invalid values
            or catalog contradictions (duplicate ids, links to unknown requirements).
    """
    source = path.name
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogFileError(source, f"cannot be read ({error})") from None
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CatalogFileError(source, f"not valid TOML ({error})") from None
    return catalog_from_dict(data, source)


def catalog_from_dict(data: dict[str, Any], source: str = "catalog") -> Catalog:
    """Build a catalog from already-parsed data (also used by tests)."""
    unknown = sorted(set(data) - TOP_LEVEL_KEYS)
    if unknown:
        raise CatalogFileError(
            source, f"unknown section(s): {', '.join(unknown)} (expected [[requirement]] and [[test_case]])"
        )
    requirements = [
        _model(Requirement, item, f"requirement[{i}]", source)
        for i, item in _items(data, "requirement", source)
    ]
    test_cases = [
        _model(TestCase, item, f"test_case[{i}]", source) for i, item in _items(data, "test_case", source)
    ]
    if not requirements:
        raise CatalogFileError(source, "contains no [[requirement]] entries")
    try:
        return Catalog.build(requirements, test_cases)
    except CatalogError as error:
        raise CatalogFileError(source, str(error)) from None


def _items(data: dict[str, Any], key: str, source: str) -> list[tuple[int, Any]]:
    """Numbered entries of an array-of-tables section (1-based, like a person counts)."""
    value = data.get(key, [])
    if not isinstance(value, list):
        raise CatalogFileError(source, f"{key} must be an array of tables ([[{key}]])")
    return list(enumerate(value, start=1))


def _model[M: (Requirement, TestCase)](kind: type[M], item: Any, where: str, source: str) -> M:
    """Validate one entry; the error names the entry, its id and the field."""
    try:
        return kind.model_validate(item)
    except ValidationError as error:
        first = error.errors()[0]
        field = ".".join(str(part) for part in first["loc"]) or "?"
        identifier = item.get("id") if isinstance(item, dict) else None
        label = f"{where} ({identifier})" if identifier else where
        raise CatalogFileError(source, f"{label}.{field}: {first['msg']}") from None
