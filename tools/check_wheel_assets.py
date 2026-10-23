"""Verify that the built wheel ships every dashboard asset, including nested report modules.

Source-checkout and editable-install browser tests cannot detect missing package data. CI runs
this against a real wheel; the container smoke separately checks the installed HTTP endpoints.
Usage: python tools/check_wheel_assets.py WHEEL_DIRECTORY
"""

from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile

STATIC = Path(__file__).parents[1] / "src" / "qualityintel" / "dashboard" / "static"


def missing_assets(wheel: Path, source: Path = STATIC) -> list[str]:
    """Compare all source assets with the wheel manifest; future subfolders are covered too."""
    expected = {
        f"qualityintel/dashboard/static/{path.relative_to(source).as_posix()}"
        for path in source.rglob("*")
        if path.is_file()
    }
    if not expected:
        raise ValueError("no source dashboard assets found")
    with ZipFile(wheel) as archive:
        return sorted(expected.difference(archive.namelist()))


def main(argv: list[str] | None = None) -> int:
    """Fail the build when any dashboard asset was left out of the distribution."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wheel_directory", type=Path)
    args = parser.parse_args(argv)
    wheels = list(args.wheel_directory.glob("*.whl"))
    if len(wheels) != 1:
        parser.error("expected exactly one built wheel")
    missing = missing_assets(wheels[0])
    if missing:
        print("Missing dashboard assets from wheel:\n" + "\n".join(missing))
        return 1
    print("All dashboard assets are included in the wheel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
