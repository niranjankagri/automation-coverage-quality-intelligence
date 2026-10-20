"""Architecture rules, checked on the source code itself.

Rule from the project plan: business logic stays independent of the dashboard. A core
module that imports the dashboard or a web framework would make coverage numbers
depend on code that is only exercised through a browser.
"""

import ast
from pathlib import Path

import pytest

import qualityintel

pytestmark = pytest.mark.unit

PACKAGE_ROOT = Path(qualityintel.__file__).parent
# Only these may depend on the dashboard: the dashboard itself and the CLI that starts it
MAY_USE_DASHBOARD = {"dashboard", "cli.py", "__main__.py"}
WEB_FRAMEWORKS = {"fastapi", "starlette", "uvicorn", "jinja2"}


def imported_modules(source: Path, package_root: Path = PACKAGE_ROOT) -> set[str]:
    """Return the absolute names of all modules a file imports, relative imports resolved.

    Args:
        source: Python file inside the package.
        package_root: Directory of the top-level package (``.../qualityintel``).
    """
    module_parts = source.relative_to(package_root.parent).with_suffix("").parts
    # A package's __init__ is the package itself; a module lives in its parent package
    package_parts = module_parts[:-1]

    names: set[str] = set()
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # "from ..x import y": every dot after the first goes one package up
                base = package_parts[: len(package_parts) - (node.level - 1)]
                module = ".".join([*base, node.module] if node.module else base)
            elif node.module:
                module = node.module
            else:
                continue
            names.add(module)
            # "from pkg import name" may import a submodule; record both, to be safe
            names.update(f"{module}.{alias.name}" for alias in node.names)
    return names


def core_modules() -> list[Path]:
    """All package files outside the dashboard and the CLI."""
    return sorted(
        path
        for path in PACKAGE_ROOT.rglob("*.py")
        if path.relative_to(PACKAGE_ROOT).parts[0] not in MAY_USE_DASHBOARD
    )


def dashboard_dependencies(names: set[str]) -> set[str]:
    """The subset of imported module names that the core must not use."""
    return {
        name
        for name in names
        if name == "qualityintel.dashboard"
        or name.startswith("qualityintel.dashboard.")
        or name.split(".")[0] in WEB_FRAMEWORKS
    }


def test_there_are_core_modules_to_check() -> None:
    """Guard against a broken path making the rule below pass on zero files."""
    assert len(core_modules()) >= 7


@pytest.mark.parametrize("source", core_modules(), ids=lambda p: p.relative_to(PACKAGE_ROOT).as_posix())
def test_core_module_does_not_depend_on_the_dashboard(source: Path) -> None:
    """No core module imports the dashboard package or a web framework."""
    forbidden = dashboard_dependencies(imported_modules(source))

    assert not forbidden, f"{source.name} imports {sorted(forbidden)}"


def test_the_rule_catches_every_import_style(tmp_path: Path) -> None:
    """A planted violation in each import style is found, so a green rule means something."""
    package = tmp_path / "qualityintel"
    (package / "gates").mkdir(parents=True)
    probe = package / "gates" / "probe.py"
    probe.write_text(
        "import fastapi.responses\n"
        "from qualityintel.dashboard import app\n"
        "from ..dashboard import views\n"
        "from . import rules\n",
        encoding="utf-8",
    )

    names = imported_modules(probe, package_root=package)

    assert "qualityintel.gates.rules" in names  # "from . import rules" resolved to its own package
    assert dashboard_dependencies(names) == {
        "fastapi.responses",
        "qualityintel.dashboard",
        "qualityintel.dashboard.app",
        "qualityintel.dashboard.views",
    }
