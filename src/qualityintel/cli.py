"""Command line entry point: ``qi <command>`` (also ``python -m qualityintel <command>``).

Exit codes are part of the contract with CI pipelines, so they are named here once:
0 = success, 2 = wrong usage or invalid configuration. Milestone 7 adds 1 = quality gate failed.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from qualityintel import __version__
from qualityintel.config import ConfigError, Settings

EXIT_OK = 0
EXIT_USAGE = 2


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with one sub-command per action."""
    parser = argparse.ArgumentParser(
        prog="qi",
        description="Automation coverage and quality intelligence for existing test frameworks.",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    commands.add_parser("version", help="print the version")
    commands.add_parser("config", help="print the settings in effect (from QI_* environment variables)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code.

    Args:
        argv: Arguments without the program name; ``sys.argv[1:]`` when omitted.

    Returns:
        The process exit code (see the module docstring).
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "version":
        print(f"qi {__version__}")
        return EXIT_OK

    if args.command == "config":
        try:
            settings = Settings.from_env()
        except ConfigError as error:
            # A clear message and a usage exit code; no traceback for a typo in a variable
            print(f"qi: configuration error: {error}", file=sys.stderr)
            return EXIT_USAGE
        print(f"database        {settings.database}")
        print(f"dashboard host  {settings.dashboard_host}")
        print(f"dashboard port  {settings.dashboard_port}")
        return EXIT_OK

    # No command given: show what is available and signal wrong usage to scripts
    parser.print_help(sys.stderr)
    return EXIT_USAGE
