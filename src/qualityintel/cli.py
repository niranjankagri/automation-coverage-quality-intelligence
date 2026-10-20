"""Command line entry point: ``qi <command>`` (also ``python -m qualityintel <command>``).

Exit codes are part of the contract with CI pipelines, so they are named here once:

- 0 = success
- 2 = wrong usage or invalid configuration
- 3 = input missing or invalid (result files, catalog); nothing was evaluated

Milestone 7 adds 1 = quality gate failed. Each command is one ``_cmd_*`` function that only
parses arguments, calls the core packages and prints; no business logic lives here.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence

from qualityintel import __version__
from qualityintel.config import ConfigError, Settings
from qualityintel.ingest.batch import Batch, import_results
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import execution_pass_rate
from qualityintel.models.results import RunContext

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3

INSPECT_COUNTS = "passed failed error skipped  pass rate"


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser with one sub-command per action."""
    parser = argparse.ArgumentParser(
        prog="qi",
        description="Automation coverage and quality intelligence for existing test frameworks.",
    )
    commands = parser.add_subparsers(dest="command", metavar="<command>")
    commands.add_parser("version", help="print the version")
    commands.add_parser("config", help="print the settings in effect (from QI_* environment variables)")

    inspect = commands.add_parser("inspect", help="read result files and print what they contain")
    add_result_arguments(inspect)
    return parser


def add_result_arguments(parser: argparse.ArgumentParser) -> None:
    """Result inputs plus the run-context options shared by every command that reads results."""
    parser.add_argument(
        "results",
        nargs="+",
        metavar="RESULTS",
        help="JUnit XML file, directory (all *.xml below it) or quoted glob pattern",
    )
    context = parser.add_argument_group("run context (overrides values found in the files)")
    for name in ("framework", "environment", "browser", "platform", "build"):
        context.add_argument(f"--{name}", metavar=name.upper())


def context_from(args: argparse.Namespace) -> RunContext | None:
    """The run context given on the command line, or ``None`` when no option was used."""
    values = {name: getattr(args, name) for name in RunContext.model_fields if getattr(args, name, None)}
    return RunContext.model_validate(values) if values else None


def report_batch_problems(batch: Batch) -> None:
    """Print duplicates and warnings (as notes) and errors to stderr."""
    for note in [*batch.duplicates, *batch.warnings]:
        print(f"qi: note: {note}", file=sys.stderr)
    for error in batch.errors:
        print(f"qi: error: {error}", file=sys.stderr)


def _cmd_version(args: argparse.Namespace) -> int:
    """Print the version."""
    print(f"qi {__version__}")
    return EXIT_OK


def _cmd_config(args: argparse.Namespace) -> int:
    """Print the settings in effect."""
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


def _cmd_inspect(args: argparse.Namespace) -> int:
    """One line per imported run: context, counts and pass rate."""
    batch = import_results(args.results, context=context_from(args))
    if batch.runs:
        print(f"{'source':<48} {'framework':<16} {'browser':<9} {'build':<9} {INSPECT_COUNTS}")
    for run in sorted(batch.runs, key=lambda r: (r.started_at is None, r.started_at, r.source)):
        counts = run.outcome_counts()
        print(
            f"{run.source[:48]:<48} {run.context.framework or '-':<16} {run.context.browser or '-':<9} "
            f"{run.context.build or '-':<9} {counts[Outcome.PASSED]:>6} {counts[Outcome.FAILED]:>6} "
            f"{counts[Outcome.ERROR]:>5} {counts[Outcome.SKIPPED]:>7}  {execution_pass_rate(counts)}"
        )
    report_batch_problems(batch)
    return EXIT_OK if batch.complete else EXIT_INPUT


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "version": _cmd_version,
    "config": _cmd_config,
    "inspect": _cmd_inspect,
}


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit code.

    Args:
        argv: Arguments without the program name; ``sys.argv[1:]`` when omitted.

    Returns:
        The process exit code (see the module docstring).
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = COMMANDS.get(args.command or "")
    if handler is None:
        # No command given: show what is available and signal wrong usage to scripts
        parser.print_help(sys.stderr)
        return EXIT_USAGE
    return handler(args)
