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
from pathlib import Path

from qualityintel import __version__
from qualityintel.config import ConfigError, Settings
from qualityintel.ingest.batch import Batch, import_results
from qualityintel.ingest.catalog_file import CatalogFileError, load_catalog
from qualityintel.models.catalog import Catalog
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import execution_pass_rate
from qualityintel.models.results import RunContext
from qualityintel.reporting.text import render_traceability
from qualityintel.traceability.coverage import Filters
from qualityintel.traceability.report import RunFilters, build_report

EXIT_OK = 0
EXIT_USAGE = 2
EXIT_INPUT = 3

INSPECT_COUNTS = "passed failed error skipped  pass rate"
CONTEXT_NAMES = tuple(RunContext.model_fields)


class UsageError(Exception):
    """A command line value is wrong in a way argparse cannot check."""


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
    add_result_arguments(inspect, required=True)

    coverage = commands.add_parser(
        "coverage", help="requirement and automation coverage, gaps and execution status"
    )
    coverage.add_argument("--catalog", required=True, type=Path, help="requirement catalog (TOML)")
    add_result_arguments(coverage, required=False)
    add_filter_arguments(coverage)
    return parser


def add_result_arguments(parser: argparse.ArgumentParser, required: bool) -> None:
    """Result inputs plus ``--context`` overrides, shared by every command that reads results."""
    parser.add_argument(
        "results",
        nargs="+" if required else "*",
        metavar="RESULTS",
        help="JUnit XML file, directory (all *.xml below it) or quoted glob pattern",
    )
    parser.add_argument(
        "--context",
        action="append",
        default=[],
        metavar="NAME=VALUE",
        help=f"run context for files that do not record it ({', '.join(CONTEXT_NAMES)}); repeatable",
    )


def add_filter_arguments(parser: argparse.ArgumentParser) -> None:
    """Scope filters; each may be repeated and an empty list means "all"."""
    group = parser.add_argument_group("scope (repeat an option to allow several values)")
    for name, what in (
        ("feature", "requirement feature"),
        ("criticality", "requirement criticality"),
        ("platform", "requirement platform"),
        ("test-type", "test case type"),
        ("framework", "test case framework and run framework"),
        ("environment", "run environment"),
        ("browser", "run browser"),
    ):
        group.add_argument(f"--{name}", action="append", default=[], metavar="VALUE", help=what)


def context_from(args: argparse.Namespace) -> RunContext | None:
    """The run context given with ``--context``, or ``None`` when none was given."""
    values: dict[str, str] = {}
    for pair in args.context:
        name, sep, value = pair.partition("=")
        if not sep or name not in CONTEXT_NAMES or not value:
            raise UsageError(
                f"--context expects NAME=VALUE with NAME one of {', '.join(CONTEXT_NAMES)}: {pair!r}"
            )
        values[name] = value
    return RunContext.model_validate(values) if values else None


def filters_from(args: argparse.Namespace) -> tuple[Filters, RunFilters]:
    """Catalog and run filters from the scope options."""
    frameworks = frozenset(args.framework)
    return (
        Filters(
            features=frozenset(args.feature),
            criticalities=frozenset(args.criticality),
            platforms=frozenset(args.platform),
            test_types=frozenset(args.test_type),
            frameworks=frameworks,
        ),
        RunFilters(
            frameworks=frameworks, environments=frozenset(args.environment), browsers=frozenset(args.browser)
        ),
    )


def report_batch_problems(batch: Batch) -> None:
    """Print duplicates and warnings (as notes) and errors to stderr."""
    for note in [*batch.duplicates, *batch.warnings]:
        print(f"qi: note: {note}", file=sys.stderr)
    for error in batch.errors:
        print(f"qi: error: {error}", file=sys.stderr)


def load_catalog_or_report(path: Path) -> Catalog | None:
    """Load the catalog; print its warnings, or its error and return ``None``."""
    try:
        catalog = load_catalog(path)
    except CatalogFileError as error:
        print(f"qi: error: {error}", file=sys.stderr)
        return None
    for warning in catalog.warnings:
        print(f"qi: note: {path.name}: {warning}", file=sys.stderr)
    return catalog


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
            f"{run.source[-48:]:<48} {run.context.framework or '-':<16} {run.context.browser or '-':<9} "
            f"{run.context.build or '-':<9} {counts[Outcome.PASSED]:>6} {counts[Outcome.FAILED]:>6} "
            f"{counts[Outcome.ERROR]:>5} {counts[Outcome.SKIPPED]:>7}  {execution_pass_rate(counts)}"
        )
    report_batch_problems(batch)
    return EXIT_OK if batch.complete else EXIT_INPUT


def _cmd_coverage(args: argparse.Namespace) -> int:
    """Coverage from the catalog; execution status too when result files are given."""
    catalog = load_catalog_or_report(args.catalog)
    if catalog is None:
        return EXIT_INPUT
    runs = []
    if args.results:
        batch = import_results(args.results, context=context_from(args))
        report_batch_problems(batch)
        if not batch.complete:
            return EXIT_INPUT
        runs = batch.runs
    filters, run_filters = filters_from(args)
    report = build_report(catalog, runs, filters, run_filters)
    print(render_traceability(report, with_execution=bool(args.results)), end="")
    return EXIT_OK


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "version": _cmd_version,
    "config": _cmd_config,
    "inspect": _cmd_inspect,
    "coverage": _cmd_coverage,
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
    try:
        return handler(args)
    except UsageError as error:
        print(f"qi: {error}", file=sys.stderr)
        return EXIT_USAGE
