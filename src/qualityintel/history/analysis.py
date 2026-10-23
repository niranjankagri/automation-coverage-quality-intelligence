"""Historical quality intelligence over many runs.

Every rule here is defined in docs/metrics.md ("History metrics") and tested with
hand-made histories. The functions take plain :class:`TestRun` objects, so they work the
same on runs from the SQLite store and on runs read straight from files.

**Comparable executions.** A test's results are only compared with results of the same
test key in the same *run context* (framework, environment, browser, platform). A failure on
Firefox says nothing about stability on Chrome.

**Window.** Classification looks at the last ``window`` verdicts (passed, failed or error; skips
are ignored) of a test in one context, oldest to newest.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from itertools import pairwise

from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio, execution_pass_rate
from qualityintel.models.results import TestResult, TestRun
from qualityintel.traceability.report import context_key

ContextKey = tuple[str | None, ...]


class Stability(StrEnum):
    """Classification of one test in one context (precedence top to bottom)."""

    INSUFFICIENT_DATA = "insufficient data"  # fewer verdicts than min_verdicts, no retry signal
    CONSISTENTLY_FAILING = "consistently failing"  # the last confirm_after verdicts all failed
    FLAKY_CANDIDATE = "flaky candidate"  # mixed results without a code change, or many flips
    NEW_FAILURE = "new failure"  # latest verdict failed after passing
    RECOVERED = "recovered"  # failed in the window, passes now
    STABLE = "stable"  # every verdict passed


@dataclass(frozen=True)
class HistorySettings:
    """Tunable thresholds (defaults documented in docs/metrics.md)."""

    window: int = 10
    min_verdicts: int = 3
    confirm_after: int = 2
    flips_for_flaky: int = 2
    slow_ratio: float = 0.5
    slow_min_seconds: float = 1.0
    slow_confirm_runs: int = 2
    min_baseline: int = 3


DEFAULTS = HistorySettings()


@dataclass(frozen=True)
class Execution:
    """One result with its run, in time order."""

    run: TestRun
    result: TestResult

    @property
    def failed(self) -> bool:
        """Failed or errored (not passed, not skipped)."""
        return self.result.outcome in (Outcome.FAILED, Outcome.ERROR)


@dataclass(frozen=True)
class TestStability:
    """Classification of one test in one context, with the evidence behind it."""

    __test__ = False  # not a pytest test class, despite the name

    key: str
    context: ContextKey
    status: Stability
    verdicts: int
    failures: int
    flips: int
    passed_after_retry: int
    mixed_builds: tuple[str, ...]
    failure_rate: Ratio
    last_outcome: Outcome
    last_failure: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class RecurringFailure:
    """The same failure signature seen in several runs.

    ``recent_runs`` counts the runs within ``recent_days`` before the newest run of the history
    (not the clock, so the same history always ranks the same); ``run_ids`` are every supporting
    run, newest first.
    """

    signature: str
    occurrences: int
    runs: int
    tests: tuple[str, ...]
    first_seen: datetime | None
    last_seen: datetime | None
    recent_runs: int = 0
    run_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class DurationRegression:
    """Latest duration clearly above the test's usual duration."""

    key: str
    context: ContextKey
    latest_seconds: float
    baseline_seconds: float
    baseline_runs: int

    @property
    def increase(self) -> float:
        """Relative increase (0.5 = 50 % slower)."""
        return self.latest_seconds / self.baseline_seconds - 1 if self.baseline_seconds else float("inf")


@dataclass(frozen=True)
class SlowTest:
    """A test with its median duration in one context."""

    key: str
    context: ContextKey
    median_seconds: float
    executions: int


@dataclass(frozen=True)
class RunPoint:
    """One run in a trend series."""

    run: TestRun
    pass_rate: Ratio
    failed: int
    total_seconds: float


@dataclass
class RunComparison:
    """What changed between two runs of comparable tests."""

    newly_failing: list[str] = field(default_factory=list)
    fixed: list[str] = field(default_factory=list)
    still_failing: list[str] = field(default_factory=list)
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    slower: list[tuple[str, float, float]] = field(default_factory=list)


# ---- timelines -----------------------------------------------------------------------------


def timelines(runs: Iterable[TestRun]) -> dict[tuple[ContextKey, str], list[Execution]]:
    """Executions per (context, test key), oldest first."""
    ordered = sorted(runs, key=_run_order)
    lines: dict[tuple[ContextKey, str], list[Execution]] = {}
    for run in ordered:
        for result in run.results:
            lines.setdefault((context_key(run.context), result.key), []).append(Execution(run, result))
    return lines


def classify(executions: Sequence[Execution], settings: HistorySettings = DEFAULTS) -> TestStability:
    """Classify one test's history in one context (rules in the module and docs/metrics.md).

    Rules, first match wins:

    1. fewer than ``min_verdicts`` verdicts and no pass-after-retry: insufficient data;
    2. the last ``confirm_after`` verdicts all failed: consistently failing (a reproduced
       failure, not flakiness);
    3. a pass after a retry inside one run, or one build that both passed and failed, or at
       least ``flips_for_flaky`` changes between pass and fail: flaky candidate;
    4. latest verdict failed: new failure;
    5. a failure earlier in the window: recovered;
    6. otherwise: stable.
    """
    if not executions:
        raise ValueError("classify needs at least one execution")
    first = executions[0]
    verdicts = [e for e in executions if e.result.outcome is not Outcome.SKIPPED][-settings.window :]
    retried = sum(1 for e in verdicts if e.result.passed_after_retry)
    failures = sum(1 for e in verdicts if e.failed)
    flips = sum(1 for a, b in pairwise(verdicts) if a.failed != b.failed)
    mixed = _mixed_builds(verdicts)
    last = executions[-1].result
    failed_messages = [e.result.failure.message for e in verdicts if e.failed and e.result.failure]
    reasons: list[str] = []

    if len(verdicts) < settings.min_verdicts and not retried:
        status = Stability.INSUFFICIENT_DATA
        reasons.append(f"{len(verdicts)} verdict(s), {settings.min_verdicts} needed")
    elif len(verdicts) >= settings.confirm_after and all(
        e.failed for e in verdicts[-settings.confirm_after :]
    ):
        status = Stability.CONSISTENTLY_FAILING
        reasons.append(f"last {settings.confirm_after} verdicts failed")
    elif retried or mixed or flips >= settings.flips_for_flaky:
        status = Stability.FLAKY_CANDIDATE
        if retried:
            reasons.append(f"passed only after a retry in {retried} run(s)")
        if mixed:
            reasons.append(f"passed and failed on the same build ({', '.join(mixed)})")
        if flips >= settings.flips_for_flaky:
            reasons.append(f"{flips} changes between pass and fail")
    elif verdicts and verdicts[-1].failed:
        status = Stability.NEW_FAILURE
        reasons.append("latest verdict failed after passing")
    elif failures:
        status = Stability.RECOVERED
        reasons.append(f"{failures} failure(s) earlier in the window, passing now")
    else:
        status = Stability.STABLE

    return TestStability(
        key=first.result.key,
        context=context_key(first.run.context),
        status=status,
        verdicts=len(verdicts),
        failures=failures,
        flips=flips,
        passed_after_retry=retried,
        mixed_builds=mixed,
        failure_rate=Ratio(numerator=failures, denominator=len(verdicts)),
        last_outcome=last.outcome,
        last_failure=failed_messages[-1] if failed_messages else "",
        reasons=tuple(reasons),
    )


def stability_report(runs: Iterable[TestRun], settings: HistorySettings = DEFAULTS) -> list[TestStability]:
    """Classification of every test in every context, most worrying first."""
    order = {status: index for index, status in enumerate(Stability)}
    rows = [classify(line, settings) for line in timelines(runs).values()]
    attention = {
        Stability.CONSISTENTLY_FAILING: 0,
        Stability.NEW_FAILURE: 1,
        Stability.FLAKY_CANDIDATE: 2,
        Stability.RECOVERED: 3,
        Stability.INSUFFICIENT_DATA: 4,
        Stability.STABLE: 5,
    }
    rows.sort(key=lambda r: (attention[r.status], order[r.status], -r.failures, r.key))
    return rows


# ---- failures ------------------------------------------------------------------------------

_VOLATILE = [
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.I), "<uuid>"),
    (re.compile(r"\b0x[0-9a-f]+\b|\b[0-9a-f]{12,}\b", re.I), "<hex>"),
    (re.compile(r"\d+(\.\d+)?"), "<n>"),
    (re.compile(r"\s+"), " "),
]


def failure_signature(result: TestResult) -> str:
    """Failure type plus the first line of the message with ids, numbers and hashes masked.

    "Timeout 15000ms exceeded" and "Timeout 30000ms exceeded" share a signature; that is the
    point: the same cause with different numbers is one recurring problem.
    """
    failure = result.failure
    if failure is None:
        return result.outcome.value
    text = (
        (failure.message or failure.text).strip().splitlines()[0] if (failure.message or failure.text) else ""
    )
    for pattern, replacement in _VOLATILE:
        text = pattern.sub(replacement, text)
    prefix = f"{failure.type}: " if failure.type else ""
    return (prefix + text.strip())[:200] or result.outcome.value


def recurring_failures(
    runs: Iterable[TestRun], min_runs: int = 2, recent_days: int = 7
) -> list[RecurringFailure]:
    """Failure signatures seen in at least ``min_runs`` different runs, ranked (docs/metrics.md).

    Rank: most runs in the last ``recent_days`` before the newest run first, then most runs in
    total, then the most recent occurrence, then most occurrences. A cause that keeps failing
    this week outranks one that failed often a month ago and stopped.
    """
    runs = list(runs)
    seen: dict[str, list[Execution]] = {}
    for run in runs:
        for result in run.results:
            if result.outcome in (Outcome.FAILED, Outcome.ERROR):
                seen.setdefault(failure_signature(result), []).append(Execution(run, result))
    newest = max((run.started_at for run in runs if run.started_at), default=None)
    since = newest - timedelta(days=recent_days) if newest else None
    found = []
    for signature, executions in seen.items():
        failing = {e.run.run_id: e.run for e in executions}
        if len(failing) < min_runs:
            continue
        dates = [e.run.started_at for e in executions if e.run.started_at]
        found.append(
            RecurringFailure(
                signature=signature,
                occurrences=len(executions),
                runs=len(failing),
                tests=tuple(sorted({e.result.key for e in executions})),
                first_seen=min(dates, default=None),
                last_seen=max(dates, default=None),
                recent_runs=sum(
                    1 for r in failing.values() if since and r.started_at and r.started_at >= since
                ),
                run_ids=tuple(r.run_id for r in sorted(failing.values(), key=_run_order, reverse=True)),
            )
        )
    return sorted(
        found,
        key=lambda f: (
            -f.recent_runs,
            -f.runs,
            -(f.last_seen.timestamp() if f.last_seen else float("-inf")),
            -f.occurrences,
            f.signature,
        ),
    )


def repeated_errors(runs: Iterable[TestRun], min_runs: int = 2) -> dict[str, int]:
    """Tests whose outcome was ``error`` (not an assertion failure) in at least ``min_runs`` runs."""
    counts: dict[str, set[str]] = {}
    for run in runs:
        for result in run.results:
            if result.outcome is Outcome.ERROR:
                counts.setdefault(result.key, set()).add(run.run_id)
    return {key: len(ids) for key, ids in sorted(counts.items()) if len(ids) >= min_runs}


# ---- durations -----------------------------------------------------------------------------


def slow_tests(runs: Iterable[TestRun], top: int = 10) -> list[SlowTest]:
    """Tests with the highest median duration per context."""
    rows = []
    for (context, key), executions in timelines(runs).items():
        durations = [e.result.duration_seconds for e in executions if e.result.duration_seconds is not None]
        if durations:
            rows.append(SlowTest(key, context, statistics.median(durations), len(durations)))
    return sorted(rows, key=lambda r: (-r.median_seconds, r.key))[:top]


def duration_regressions(
    runs: Iterable[TestRun], settings: HistorySettings = DEFAULTS
) -> list[DurationRegression]:
    """Tests that got clearly slower and stayed slower.

    For each test in each context: the *recent* durations are the last ``slow_confirm_runs``;
    the *baseline* is the median of up to ``window`` durations before them (at least
    ``min_baseline``). A regression is reported only when **every** recent duration is above
    baseline x (1 + ``slow_ratio``) **and** at least ``slow_min_seconds`` above the baseline.

    Requiring consecutive slow runs keeps one noisy run out: in parallel suites the time a
    test reports depends on what ran beside it (seen in the sample data: the 19 Oct nightly
    has individual tests 5x slower while the suite's wall time did not change).
    """
    found = []
    recent_count = max(1, settings.slow_confirm_runs)
    for (context, key), executions in timelines(runs).items():
        timed = [e.result.duration_seconds for e in executions if e.result.duration_seconds is not None]
        if len(timed) < settings.min_baseline + recent_count:
            continue
        recent, earlier = timed[-recent_count:], timed[:-recent_count][-settings.window :]
        baseline = statistics.median(earlier)
        if all(
            value > baseline * (1 + settings.slow_ratio) and value - baseline >= settings.slow_min_seconds
            for value in recent
        ):
            found.append(DurationRegression(key, context, recent[-1], baseline, len(earlier)))
    return sorted(found, key=lambda r: -(r.latest_seconds - r.baseline_seconds))


# ---- runs ----------------------------------------------------------------------------------


def trend(runs: Iterable[TestRun]) -> dict[ContextKey, list[RunPoint]]:
    """Pass rate, failures and total duration per run, per context, oldest first."""
    series: dict[ContextKey, list[RunPoint]] = {}
    for run in sorted(runs, key=_run_order):
        counts = run.outcome_counts()
        series.setdefault(context_key(run.context), []).append(
            RunPoint(
                run=run,
                pass_rate=execution_pass_rate(counts),
                failed=counts[Outcome.FAILED] + counts[Outcome.ERROR],
                total_seconds=sum(r.duration_seconds or 0.0 for r in run.results),
            )
        )
    return series


def compare_runs(base: TestRun, head: TestRun, settings: HistorySettings = DEFAULTS) -> RunComparison:
    """Differences from ``base`` to ``head`` by test key (both runs should share a context)."""
    before = {r.key: r for r in base.results}
    after = {r.key: r for r in head.results}
    comparison = RunComparison()
    for key in sorted(after.keys() - before.keys()):
        comparison.added.append(key)
    for key in sorted(before.keys() - after.keys()):
        comparison.removed.append(key)
    for key in sorted(before.keys() & after.keys()):
        old, new = before[key], after[key]
        old_bad = old.outcome in (Outcome.FAILED, Outcome.ERROR)
        new_bad = new.outcome in (Outcome.FAILED, Outcome.ERROR)
        if new_bad and not old_bad:
            comparison.newly_failing.append(key)
        elif old_bad and not new_bad and new.outcome is Outcome.PASSED:
            comparison.fixed.append(key)
        elif old_bad and new_bad:
            comparison.still_failing.append(key)
        if (
            old.duration_seconds is not None
            and new.duration_seconds is not None
            and new.duration_seconds > old.duration_seconds * (1 + settings.slow_ratio)
            and new.duration_seconds - old.duration_seconds >= settings.slow_min_seconds
        ):
            comparison.slower.append((key, old.duration_seconds, new.duration_seconds))
    return comparison


def summary_by(runs: Iterable[TestRun], dimension: str) -> dict[str, tuple[int, Ratio]]:
    """Runs and pooled pass rate per value of one context field (build, environment, framework ...)."""
    pooled: dict[str, dict[Outcome, int]] = {}
    count: dict[str, int] = {}
    for run in runs:
        value = getattr(run.context, dimension) or "unspecified"
        totals = pooled.setdefault(value, dict.fromkeys(Outcome, 0))
        for outcome, n in run.outcome_counts().items():
            totals[outcome] += n
        count[value] = count.get(value, 0) + 1
    return {value: (count[value], execution_pass_rate(pooled[value])) for value in sorted(pooled)}


# ---- helpers -------------------------------------------------------------------------------


def _mixed_builds(verdicts: Sequence[Execution]) -> tuple[str, ...]:
    """Builds on which this test both passed and failed (no code change between them)."""
    outcomes: dict[str, set[bool]] = {}
    for e in verdicts:
        if e.run.context.build:
            outcomes.setdefault(e.run.context.build, set()).add(e.failed)
    return tuple(sorted(build for build, seen in outcomes.items() if seen == {True, False}))


def _run_order(run: TestRun) -> tuple[bool, datetime | None, str]:
    """Undated runs first, then by start time and source."""
    return (run.started_at is not None, run.started_at, run.source)
