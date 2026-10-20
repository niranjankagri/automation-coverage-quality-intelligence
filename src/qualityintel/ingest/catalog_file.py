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
    """Load and validate a catalog file and the files it includes.

    A catalog may start with ``include = ["requirements.toml"]``: paths relative to the catalog's
    folder whose ``[[requirement]]`` and ``[[test_case]]`` entries are added to its own. This lets
    a tool-generated requirements file (``qi requirements import``) sit next to hand-written test
    cases without either overwriting the other. Included files cannot include further files.

    Raises:
        CatalogFileError: Unreadable file, TOML syntax error, unknown sections, invalid values,
            a bad include, or catalog contradictions (duplicate ids, links to unknown requirements).
    """
    data = read_toml(path)
    includes = data.pop("include", [])
    if not isinstance(includes, list) or not all(isinstance(item, str) for item in includes):
        raise CatalogFileError(
            path.name, 'include must be a list of file names, e.g. include = ["requirements.toml"]'
        )

    requirements, test_cases = _entries(data, path.name)
    origin = {requirement.id: path.name for requirement in requirements}
    for name in includes:
        included = _include_path(path, name)
        part = read_toml(included)
        if "include" in part:
            raise CatalogFileError(included.name, "an included file cannot include further files")
        more_requirements, more_cases = _entries(part, included.name)
        for requirement in more_requirements:
            if requirement.id in origin:
                raise CatalogFileError(
                    included.name, f"requirement {requirement.id} is also defined in {origin[requirement.id]}"
                )
            origin[requirement.id] = included.name
        requirements += more_requirements
        test_cases += more_cases
    return _build(requirements, test_cases, path.name)


def read_toml(path: Path) -> dict[str, Any]:
    """Parse a TOML file; problems become :class:`CatalogFileError` naming the file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise CatalogFileError(path.name, f"cannot be read ({error})") from None
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError as error:
        raise CatalogFileError(path.name, f"not valid TOML ({error})") from None


def catalog_from_dict(data: dict[str, Any], source: str = "catalog") -> Catalog:
    """Build a catalog from already-parsed data (also used by tests); includes are not resolved."""
    requirements, test_cases = _entries(data, source)
    return _build(requirements, test_cases, source)


def _entries(data: dict[str, Any], source: str) -> tuple[list[Requirement], list[TestCase]]:
    """Validated requirement and test case entries of one file."""
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
    return requirements, test_cases


def _build(requirements: list[Requirement], test_cases: list[TestCase], source: str) -> Catalog:
    """The checked catalog; contradictions name the (main) file."""
    if not requirements:
        raise CatalogFileError(source, "contains no [[requirement]] entries")
    try:
        return Catalog.build(requirements, test_cases)
    except CatalogError as error:
        raise CatalogFileError(source, str(error)) from None


def _include_path(catalog: Path, name: str) -> Path:
    """Resolve an include next to the catalog; absolute paths and '..' are refused (portable catalogs)."""
    relative = Path(name)
    if relative.is_absolute() or ".." in relative.parts or not name.strip():
        raise CatalogFileError(
            catalog.name, f"include {name!r} must be a file name or a path inside the catalog's folder"
        )
    return catalog.parent / relative


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


def requirements_by_file(path: Path) -> dict[str, list[str]]:
    """Requirement ids per file (the catalog and each include), for import conflict checks."""
    data = read_toml(path)
    includes = data.pop("include", [])
    found = {path.name: [r.id for r in _entries(data, path.name)[0]]}
    for name in includes if isinstance(includes, list) else []:
        included = _include_path(path, str(name))
        if included.exists():
            part = read_toml(included)
            part.pop("include", None)
            found[included.name] = [r.id for r in _entries(part, included.name)[0]]
    return found


def requirements_in(path: Path) -> list[Requirement]:
    """The requirement entries of one file (no includes, no other checks); empty if it does not exist."""
    if not path.exists():
        return []
    data = read_toml(path)
    data.pop("include", None)
    return _entries(data, path.name)[0]
