"""Command line entry point: ``qi <command>`` (also ``python -m qualityintel <command>``).

Exit codes are part of the contract with CI pipelines, so they are named here once:

- 0 = success (for ``qi gate``: every configured rule passed)
- 1 = ``qi gate`` only: at least one configured rule failed
- 2 = wrong usage or invalid configuration (including an invalid gate file)
- 3 = input missing or invalid (result files, catalog); no decision was possible
- 4 = internal error (a bug in qi); never confused with a gate decision

Each command is one ``_cmd_*`` function that only parses arguments, calls the core packages
and prints; no business logic lives here.
"""

from __future__ import annotations

import argparse
import ipaddress
import os
import sys
import traceback
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path

from qualityintel import __version__
from qualityintel.collect.audit import audit, render_markdown, render_text
from qualityintel.collect.collector import collect
from qualityintel.collect.config import ProducersError, load_producers
from qualityintel.collect.github import GitHubActions
from qualityintel.config import ConfigError, Settings
from qualityintel.gates.config import GateConfigError, load_gate_config
from qualityintel.gates.evaluate import evaluate
from qualityintel.history.analysis import (
    HistorySettings,
    compare_runs,
    duration_regressions,
    recurring_failures,
    repeated_errors,
    slow_tests,
    stability_report,
    summary_by,
    trend,
)
from qualityintel.history.store import HistoryError, HistoryStore
from qualityintel.history.trends import coverage_snapshot
from qualityintel.ingest.batch import Batch, import_pipeline, import_results
from qualityintel.ingest.catalog_file import (
    CatalogFileError,
    load_catalog,
    requirements_by_file,
    requirements_in,
)
from qualityintel.ingest.errors import IngestError
from qualityintel.ingest.requirements_csv import (
    is_generated,
    plan_import,
    read_requirements_csv,
    render_requirements_toml,
)
from qualityintel.live import LiveData, LoadError, Sources, load_snapshot
from qualityintel.models.catalog import Catalog
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import execution_pass_rate
from qualityintel.models.results import RunContext, TestRun
from qualityintel.reporting.gate_report import (
    gate_document,
    incomplete_document,
    to_html,
    to_json,
    to_markdown,
    to_text,
)
from qualityintel.reporting.text import render_comparison, render_history, render_traceability
from qualityintel.traceability.coverage import Filters
from qualityintel.traceability.pipelines import pipeline_execution
from qualityintel.traceability.report import RunFilters, build_report

EXIT_OK = 0
EXIT_GATE_FAILED = 1
EXIT_USAGE = 2
EXIT_INPUT = 3
EXIT_INTERNAL = 4

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

    dashboard = commands.add_parser("dashboard", help="serve the read-only web dashboard")
    dashboard.add_argument("--catalog", required=True, type=Path, help="requirement catalog (TOML)")
    add_result_arguments(dashboard, required=False)
    dashboard.add_argument("--host", help="address to listen on (default: QI_DASHBOARD_HOST or 127.0.0.1)")
    dashboard.add_argument("--port", type=int, help="port (default: QI_DASHBOARD_PORT or 8000)")
    dashboard.add_argument(
        "--database", type=Path, help="also load every run stored in this history database"
    )
    dashboard.add_argument(
        "--gate", type=Path, metavar="FILE", help="release gate whose decision the overview shows (TOML)"
    )
    dashboard.add_argument(
        "--refresh",
        type=float,
        metavar="SECONDS",
        help="check the sources for new data every SECONDS, 0 = never (default: QI_REFRESH_SECONDS or 30)",
    )

    gate = commands.add_parser("gate", help="decide a release quality gate (exit code 0 / 1 / 3)")
    gate.add_argument("--catalog", required=True, type=Path, help="requirement catalog (TOML)")
    gate.add_argument("--config", required=True, type=Path, help="gate definition (TOML)")
    add_result_arguments(gate, required=False)
    add_pipeline_arguments(gate)
    gate.add_argument(
        "--database",
        type=Path,
        help="decide on a collected pipeline (--pipeline ID) from this history database (docs/collection.md)",
    )
    gate.add_argument("--json", type=Path, metavar="FILE", help="write the machine-readable report")
    gate.add_argument("--html", type=Path, metavar="FILE", help="write the HTML report")
    gate.add_argument(
        "--summary", type=Path, metavar="FILE", help="append a Markdown summary (e.g. $GITHUB_STEP_SUMMARY)"
    )

    collector = commands.add_parser(
        "collect", help="collect results of CI pipeline runs into history (docs/collection.md)"
    )
    collector.add_argument(
        "--producers", type=Path, default=Path("config/producers.toml"), help="producers file (TOML)"
    )
    collector.add_argument(
        "--database", type=Path, help="SQLite file (default: QI_DATABASE or .qi/quality.db)"
    )
    collector.add_argument(
        "--days", type=int, default=7, help="runs started in the last N days (1-90, default 7)"
    )
    collector.add_argument(
        "--repository", action="append", default=[], metavar="NAME", help="only this producer; repeatable"
    )
    collector.add_argument(
        "--audit-only", action="store_true", help="no downloads: print the ingestion audit of the database"
    )
    collector.add_argument("--summary", type=Path, metavar="FILE", help="append the audit as Markdown")

    requirements = commands.add_parser("requirements", help="import requirements from a CSV file")
    requirement_commands = requirements.add_subparsers(
        dest="requirements_command", metavar="<action>", required=True
    )
    csv_import = requirement_commands.add_parser(
        "import", help="preview (default) or apply a CSV import into a generated requirements file"
    )
    csv_import.add_argument("csv", type=Path, metavar="CSV", help="requirements CSV (UTF-8, header row)")
    csv_import.add_argument(
        "--into", required=True, type=Path, help="generated requirements file (TOML); created if missing"
    )
    csv_import.add_argument(
        "--catalog",
        type=Path,
        help="catalog that includes --into: checked for duplicate ids and still-valid links",
    )
    csv_import.add_argument("--apply", action="store_true", help="write the file (without it: preview only)")

    history = commands.add_parser(
        "history", help="execution history: import runs, stability report, compare runs"
    )
    history_commands = history.add_subparsers(dest="history_command", metavar="<action>", required=True)

    store = history_commands.add_parser("import", help="store result files in the history database")
    add_result_arguments(store, required=False)
    add_pipeline_arguments(store)
    store.add_argument(
        "--catalog",
        type=Path,
        help="also record the catalog's coverage (only when it changed since the last record)",
    )
    store.add_argument("--database", type=Path, help="SQLite file (default: QI_DATABASE or .qi/quality.db)")

    report = history_commands.add_parser("report", help="stability, recurring failures, durations, trends")
    add_result_arguments(report, required=False)
    report.add_argument("--database", type=Path, help="SQLite file (default: QI_DATABASE or .qi/quality.db)")
    report.add_argument("--no-database", action="store_true", help="use only the result files given")
    report.add_argument(
        "--window", type=int, default=HistorySettings.window, help="verdicts per test to look at"
    )
    for name in ("framework", "environment", "browser"):
        report.add_argument(
            f"--{name}", action="append", default=[], metavar="VALUE", help=f"only runs with this {name}"
        )

    compare = history_commands.add_parser("compare", help="what changed between two stored runs")
    compare.add_argument("base", help="run id (or its first characters) or the end of its source name")
    compare.add_argument("head", help="run id (or its first characters) or the end of its source name")
    compare.add_argument("--database", type=Path, help="SQLite file (default: QI_DATABASE or .qi/quality.db)")
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


def add_pipeline_arguments(parser: argparse.ArgumentParser) -> None:
    """Options that import results as the jobs of one pipeline execution (docs/pipelines.md)."""
    group = parser.add_argument_group("pipeline execution (instead of RESULTS)")
    group.add_argument("--pipeline", metavar="ID", help="pipeline execution id, e.g. the CI run id")
    group.add_argument(
        "--job",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="results of one job (file, directory or quoted pattern); repeat per job or path",
    )
    group.add_argument("--attempt", type=int, default=1, help="re-run number of the jobs given (default 1)")
    group.add_argument("--branch", help="branch the pipeline ran on")
    group.add_argument("--commit", help="commit the pipeline tested")
    group.add_argument("--repository", metavar="OWNER/NAME", help="repository the pipeline belongs to")


def read_inputs(args: argparse.Namespace) -> Batch:
    """Result inputs as given: plain RESULTS, or ``--pipeline`` with ``--job NAME=PATH``."""
    if args.pipeline is None:
        if args.job or args.branch or args.commit or args.repository or args.attempt != 1:
            raise UsageError("--job, --attempt, --branch, --commit and --repository need --pipeline")
        if not args.results:
            raise UsageError("give result files, or --pipeline with --job NAME=PATH")
        return import_results(args.results, context=context_from(args))
    if args.results:
        raise UsageError("with --pipeline, give every result input as --job NAME=PATH (to know its job)")
    if not args.job:
        raise UsageError("--pipeline needs at least one --job NAME=PATH")
    if args.attempt < 1:
        raise UsageError("--attempt must be at least 1")
    jobs: dict[str, list[str]] = {}
    for pair in args.job:
        name, sep, path = pair.partition("=")
        if not sep or not name.strip() or not path:
            raise UsageError(f"--job expects NAME=PATH: {pair!r}")
        jobs.setdefault(name.strip(), []).append(path)
    return import_pipeline(
        jobs,
        args.pipeline,
        attempt=args.attempt,
        branch=args.branch,
        commit=args.commit,
        context=context_from(args),
        repository=args.repository,
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
    print(f"dashboard user  {settings.dashboard_user}")
    # Never the value: only whether one is set
    print(f"dashboard login {'password set' if settings.dashboard_password else 'off (this machine only)'}")
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


def database_path(args: argparse.Namespace) -> Path:
    """``--database`` if given, else the configured default (may raise ConfigError)."""
    return args.database if args.database is not None else Settings.from_env().database


def open_store(path: Path) -> HistoryStore | None:
    """Open the history database; print the reason and return ``None`` when it cannot be used."""
    try:
        return HistoryStore(path)
    except HistoryError as error:
        print(f"qi: error: {error}", file=sys.stderr)
        return None


def find_run(runs: list[TestRun], reference: str) -> TestRun:
    """A stored run by id prefix (>= 6 characters) or by the end of its source name."""
    matches = [r for r in runs if len(reference) >= 6 and r.run_id.startswith(reference)]
    matches = matches or [r for r in runs if r.source.endswith(reference)]
    if len(matches) != 1:
        found = "no run" if not matches else f"{len(matches)} runs"
        raise UsageError(f"{found} match {reference!r}; use more characters of the run id or file name")
    return matches[0]


def _cmd_history(args: argparse.Namespace) -> int:
    """Dispatch ``qi history <action>``."""
    try:
        path = database_path(args)
    except ConfigError as error:
        print(f"qi: configuration error: {error}", file=sys.stderr)
        return EXIT_USAGE

    if args.history_command == "import":
        batch = read_inputs(args)
        report_batch_problems(batch)
        if not batch.complete:
            return EXIT_INPUT
        catalog = None
        if args.catalog is not None:
            catalog = load_catalog_or_report(args.catalog)
            if catalog is None:
                return EXIT_INPUT
        store = open_store(path)
        if store is None:
            return EXIT_INPUT
        with store:
            refused = store.conflicting_jobs(batch.runs)
            if refused:
                for message in refused:
                    print(f"qi: error: {message}", file=sys.stderr)
                return EXIT_INPUT
            added, known = store.add_all(batch.runs)
            run_count, result_count = store.count()
            if catalog is not None:
                recorded = store.add_snapshot(coverage_snapshot(catalog, args.catalog.name))
                print(
                    "recorded a coverage snapshot"
                    if recorded
                    else "coverage unchanged since the last snapshot"
                )
        print(
            f"added {added} run(s), {known} already stored; "
            f"{path} now holds {run_count} runs, {result_count} results"
        )
        return EXIT_OK

    if args.history_command == "report":
        runs: list[TestRun] = []
        if not args.no_database:
            store = open_store(path)
            if store is None:
                return EXIT_INPUT
            with store:
                runs = store.runs()
        if args.results:
            batch = import_results(args.results, context=context_from(args))
            report_batch_problems(batch)
            if not batch.complete:
                return EXIT_INPUT
            stored_ids = {r.run_id for r in runs}
            runs += [r for r in batch.runs if r.run_id not in stored_ids]
        filters = RunFilters(
            frameworks=frozenset(args.framework),
            environments=frozenset(args.environment),
            browsers=frozenset(args.browser),
        )
        runs = [r for r in runs if filters.keeps(r)]
        if not runs:
            print("qi: error: no runs to analyse (import some with `qi history import`)", file=sys.stderr)
            return EXIT_INPUT
        if args.window < 1:
            raise UsageError("--window must be at least 1")
        settings = HistorySettings(window=args.window)
        print(
            render_history(
                stability_report(runs, settings),
                recurring_failures(runs),
                repeated_errors(runs),
                duration_regressions(runs, settings),
                slow_tests(runs),
                trend(runs),
                summary_by(runs, "build"),
            ),
            end="",
        )
        return EXIT_OK

    # compare
    store = open_store(path)
    if store is None:
        return EXIT_INPUT
    with store:
        stored = store.runs()
    base, head = find_run(stored, args.base), find_run(stored, args.head)
    print(render_comparison(base, head, compare_runs(base, head)), end="")
    return EXIT_OK


def _cmd_gate(args: argparse.Namespace) -> int:
    """Evaluate a gate and write its reports; the exit code is the verdict."""
    try:
        config = load_gate_config(args.config)
    except GateConfigError as error:
        print(f"qi: configuration error: {error}", file=sys.stderr)
        return EXIT_USAGE
    try:
        catalog = load_catalog(args.catalog)
    except CatalogFileError as error:
        # Even without a catalog the reports are written, so CI shows why no decision was made
        document = incomplete_document(config.name, [str(error)], args.catalog.name)
        _write_gate_reports(document, args)
        print(to_text(document), end="")
        return EXIT_INPUT
    for warning in catalog.warnings:
        print(f"qi: note: {args.catalog.name}: {warning}", file=sys.stderr)

    problems: list[str] = []
    runs: list[TestRun] = []
    execution = None
    # Any input option is checked, so a --job without --pipeline is an error, not ignored
    pipeline_options = (args.pipeline, args.job, args.branch, args.commit, args.repository, args.attempt != 1)
    if args.database is not None:
        if args.pipeline is None or args.job or args.results:
            raise UsageError(
                "--database decides on one collected pipeline: give --pipeline ID, no files or --job"
            )
        store = open_store(args.database)
        if store is None:
            return EXIT_INPUT
        with store:
            stored = store.runs()
            records = [c for c in store.collections() if c.pipeline_id == args.pipeline]
        latest = max(records, key=lambda c: c.attempt, default=None)
        if latest is not None and latest.state == "incomplete":
            # What collection found missing or unreadable is missing input for the gate too
            problems += [
                f"pipeline {args.pipeline} attempt {latest.attempt}: {p}" for p in latest.problems
            ] or [f"pipeline {args.pipeline} attempt {latest.attempt} was collected incomplete"]
        execution = pipeline_execution(stored, args.pipeline, config.pipeline.jobs)
        runs = execution.runs
    elif args.results or any(pipeline_options):
        batch = read_inputs(args)
        report_batch_problems(batch)
        problems = [str(error) for error in batch.errors]
        runs = batch.runs
        if args.pipeline is not None:
            # The gate file's job list wins; without one, the jobs named on the command line
            expected = config.pipeline.jobs or tuple(
                dict.fromkeys(p.partition("=")[0].strip() for p in args.job)
            )
            execution = pipeline_execution(runs, args.pipeline, expected)
            runs = execution.runs
    scope = config.scope
    frameworks = frozenset(scope.framework)
    report = build_report(
        catalog,
        runs,
        Filters(
            features=frozenset(scope.feature),
            criticalities=frozenset(scope.criticality),
            platforms=frozenset(scope.platform),
            test_types=frozenset(scope.test_type),
            frameworks=frameworks,
        ),
        RunFilters(
            frameworks=frameworks,
            environments=frozenset(scope.environment),
            browsers=frozenset(scope.browser),
        ),
        # A pipeline execution is one execution: all its runs count (several files per job, or
        # two jobs in the same context), not only the latest per context
        one_execution=execution is not None,
    )
    result = evaluate(report, config, problems, execution)
    document = gate_document(result, report, args.catalog.name)
    _write_gate_reports(document, args)
    print(to_text(document), end="")
    return result.exit_code


def _write_gate_reports(document: dict[str, object], args: argparse.Namespace) -> None:
    """Write the requested report files (folders are created; the summary is appended)."""
    for path, text in ((args.json, to_json(document)), (args.html, to_html(document))):
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
    if args.summary is not None:
        with args.summary.open("a", encoding="utf-8") as summary:
            summary.write(to_markdown(document))


def _cmd_requirements(args: argparse.Namespace) -> int:
    """Preview or apply a requirements CSV import (all-or-nothing; see docs/requirements-import.md)."""
    target: Path = args.into
    if not is_generated(target):
        print(
            f"qi: error: {target.name} was not written by `qi requirements import`; "
            "refusing to overwrite a hand-written file (use a separate file and include it from the catalog)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    try:
        parsed = read_requirements_csv(args.csv)
        existing = requirements_in(target)
        elsewhere = _ids_defined_elsewhere(args.catalog, target)
    except IngestError as error:
        print(f"qi: error: {error}", file=sys.stderr)
        return EXIT_INPUT
    plan = plan_import(parsed.requirements, existing, elsewhere)

    mode = "APPLY" if args.apply else "PREVIEW (nothing written; add --apply to write)"
    print(f"{parsed.source} -> {target.name}: {mode}")
    print(f"  rows {parsed.rows}: {len(parsed.requirements)} valid, {len(parsed.errors)} invalid")
    print(
        f"  new {len(plan.added)}, changed {len(plan.changed)}, unchanged {len(plan.unchanged)}, "
        f"kept (in {target.name}, not in the file) {len(plan.kept)}"
    )
    for requirement in plan.added:
        print(f"  + {requirement.id}  {requirement.title}")
    for before, _, fields in plan.changed:
        print(f"  ~ {before.id}  changed: {', '.join(fields)}")
    for row_error in parsed.errors:
        print(f"qi: error: {parsed.source}: {row_error}", file=sys.stderr)
    for identifier in plan.conflicts:
        print(f"qi: error: {identifier} is already defined in another catalog file", file=sys.stderr)
    if parsed.errors or plan.conflicts:
        print("  nothing written: fix the problems above and run the import again")
        return EXIT_INPUT
    if not args.apply:
        return EXIT_OK

    previous = target.read_text(encoding="utf-8") if target.exists() else None
    text = render_requirements_toml(plan.result, parsed.source)
    if text == previous:
        print(f"  {target.name} is already up to date")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"  wrote {target} ({len(plan.result)} requirements)")
    if args.catalog is not None:
        try:
            catalog = load_catalog(args.catalog)
        except IngestError as problem:
            # The import broke the catalog: put the old file back and say why
            if previous is None:
                target.unlink()
            else:
                target.write_text(previous, encoding="utf-8")
            print(
                f"qi: error: the catalog would no longer load, {target.name} restored: {problem}",
                file=sys.stderr,
            )
            return EXIT_INPUT
        counts = f"{len(catalog.requirements)} requirements, {len(catalog.links)} links"
        print(f"  {args.catalog.name} loads: {counts}")
    return EXIT_OK


def _ids_defined_elsewhere(catalog: Path | None, target: Path) -> set[str]:
    """Requirement ids the catalog (or its other includes) defines outside the target file."""
    if catalog is None:
        return set()
    return {
        identifier
        for name, ids in requirements_by_file(catalog).items()
        if name != target.name
        for identifier in ids
    }


def _cmd_dashboard(args: argparse.Namespace) -> int:
    """Load the data once, then serve it until interrupted (Ctrl+C)."""
    try:
        settings = Settings.from_env()
    except ConfigError as error:
        print(f"qi: configuration error: {error}", file=sys.stderr)
        return EXIT_USAGE
    catalog = load_catalog_or_report(args.catalog)
    if catalog is None:
        return EXIT_INPUT
    if args.results:
        batch = import_results(args.results, context=context_from(args))
        report_batch_problems(batch)
        if not batch.complete:
            return EXIT_INPUT
    if args.database is not None:
        store = open_store(args.database)
        if store is None:
            return EXIT_INPUT
        store.close()
    refresh = settings.refresh_seconds if args.refresh is None else args.refresh
    if refresh < 0:
        raise UsageError("--refresh must be 0 (off) or a number of seconds")
    sources = Sources(args.catalog, args.database, tuple(args.results), context_from(args), args.gate)
    try:
        first = load_snapshot(sources)
    except LoadError as error:
        print(f"qi: error: {error}", file=sys.stderr)
        return EXIT_INPUT
    runs = first.workspace.runs
    # Imported here so the other commands start without loading the web stack
    import uvicorn

    from qualityintel.dashboard.app import create_app

    host = args.host or settings.dashboard_host
    port = args.port or settings.dashboard_port
    credentials = (
        (settings.dashboard_user, settings.dashboard_password) if settings.dashboard_password else None
    )
    if credentials is None and not is_loopback(host):
        print(
            f"qi: error: refusing to serve the dashboard on {host} without a login: anyone who can reach "
            "the port could read everything. Set QI_DASHBOARD_PASSWORD (and put TLS in front), or use "
            "127.0.0.1 (docs/security.md)",
            file=sys.stderr,
        )
        return EXIT_USAGE
    login = f", login required (user {credentials[0]})" if credentials else ""
    print(
        f"qi: dashboard on http://{host}:{port}  "
        f"({len(catalog.requirements)} requirements, {len(runs)} runs{login})"
    )
    if credentials and not is_loopback(host):
        print(
            "qi: note: basic authentication sends the password with every request; "
            "serve it behind TLS (a reverse proxy)",
            file=sys.stderr,
        )
    live = LiveData(first, sources, interval_seconds=refresh)
    app = create_app(live, credentials, settings.collection_hours, settings.collection_url)
    uvicorn.run(app, host=host, port=port, log_level="warning")
    return EXIT_OK


def is_loopback(host: str) -> bool:
    """True for addresses only this machine can reach (127.0.0.0/8, ::1, localhost)."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False  # a host name: it may resolve to anything


def _cmd_collect(args: argparse.Namespace) -> int:
    """Collect completed pipeline runs of every producer; print the ingestion audit.

    Exit code 0 when every producer could be read (incomplete pipelines are recorded, not
    errors), 3 when a producer or a run could not be read (it is tried again next time), 2 for
    wrong usage or an invalid producers file.
    """
    if not 1 <= args.days <= 90:
        raise UsageError("--days must be between 1 and 90")
    try:
        producers = load_producers(args.producers)
        path = database_path(args)
    except (ProducersError, ConfigError) as error:
        print(f"qi: configuration error: {error}", file=sys.stderr)
        return EXIT_USAGE
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not args.audit_only and not token:
        print("qi: error: set GITHUB_TOKEN (GitHub needs a token to download artifacts)", file=sys.stderr)
        return EXIT_USAGE
    # Whole days: GitHub filters runs by creation date, and the audit must count the same runs
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    since = today - timedelta(days=args.days)
    store = open_store(path)
    if store is None:
        return EXIT_INPUT
    with store:
        outcomes = (
            [] if args.audit_only else collect(producers, GitHubActions(token), store, since, args.repository)
        )
        rows = audit(store.collections(), [p.repository for p in producers.producer], since, outcomes)
    for outcome in outcomes:
        print(
            f"{outcome.repository} {outcome.workflow}: {outcome.seen} completed run(s), "
            f"{len(outcome.collected)} collected, "
            f"{outcome.already_collected} collected before"
        )
    print(render_text(rows, since), end="")
    if args.summary is not None:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        with args.summary.open("a", encoding="utf-8") as summary:
            summary.write(render_markdown(rows, since))
    return EXIT_INPUT if any(outcome.errors for outcome in outcomes) else EXIT_OK


COMMANDS: dict[str, Callable[[argparse.Namespace], int]] = {
    "collect": _cmd_collect,
    "version": _cmd_version,
    "config": _cmd_config,
    "inspect": _cmd_inspect,
    "coverage": _cmd_coverage,
    "dashboard": _cmd_dashboard,
    "history": _cmd_history,
    "gate": _cmd_gate,
    "requirements": _cmd_requirements,
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
    except Exception:
        # A crash must not look like "gate failed" (1) to a pipeline: it gets its own code
        traceback.print_exc()
        print("qi: internal error (exit code 4); please report it with the traceback above", file=sys.stderr)
        return EXIT_INTERNAL
