"""Security rule, checked on the source code: imported content is data, never code (docs/security.md).

Result files, catalogs, CSV exports and gate files come from outside. Nothing in the package may
turn text into running code or start other programs, so no input can do either.
"""

import ast
from pathlib import Path

import pytest

import qualityintel

pytestmark = pytest.mark.unit

PACKAGE_ROOT = Path(qualityintel.__file__).parent
FORBIDDEN_MODULES = {"pickle", "marshal", "shelve", "subprocess", "yaml", "ctypes"}
# Builtins that run text as code (called by bare name; re.compile is fine)
FORBIDDEN_BUILTINS = {"eval", "exec", "compile", "__import__"}
# Module functions that run programs or load code by name
FORBIDDEN_ATTRIBUTES = {("os", "system"), ("os", "popen"), ("importlib", "import_module")}


def violations(source: Path) -> list[str]:
    """Forbidden imports and calls in one file, as ``line: what``."""
    found = []
    for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in FORBIDDEN_BUILTINS:
                found.append(f"{node.lineno}: call to {func.id}()")
            elif (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and (func.value.id, func.attr) in FORBIDDEN_ATTRIBUTES
            ):
                found.append(f"{node.lineno}: call to {func.value.id}.{func.attr}()")
            continue
        else:
            continue
        found += [f"{node.lineno}: import {n}" for n in names if n.split(".")[0] in FORBIDDEN_MODULES]
    return found


@pytest.mark.parametrize(
    "source", sorted(PACKAGE_ROOT.rglob("*.py")), ids=lambda p: p.relative_to(PACKAGE_ROOT).as_posix()
)
def test_no_module_can_execute_input(source: Path) -> None:
    """No eval/exec/compile, no pickle-style loaders, no subprocesses anywhere in the package."""
    assert violations(source) == []


def test_the_rule_finds_what_it_forbids(tmp_path: Path) -> None:
    """The checker itself catches each forbidden form (so an empty result means something)."""
    probe = tmp_path / "probe.py"
    probe.write_text(
        "import pickle\nfrom subprocess import run\nimport os\neval('1')\nos.system('x')\n"
        "re.compile('x')\nimportlib.import_module('y')\ncompile('1', 'f', 'eval')\n",
        encoding="utf-8",
    )

    assert violations(probe) == [
        "1: import pickle",
        "2: import subprocess",
        "4: call to eval()",
        "5: call to os.system()",
        "7: call to importlib.import_module()",
        "8: call to compile()",
    ]  # line 6, re.compile, is allowed
