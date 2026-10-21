"""Which executed result belongs to which catalog test case.

A result belongs to a test case when

1. the result carries an explicit test id equal to the case id (JUnit property ``test_id`` or
   ``[TC-1]`` in the name), or
2. its key (``classname::name``) matches one of the case's ``automated_by`` patterns.

Explicit ids win: a result with an explicit id that is in the catalog is not pattern-matched
at all, so a stray pattern cannot pull it into a second case. Explicit ids that are not in the
catalog are counted (``unknown_ids``) and the result falls back to pattern matching. A result
may match several cases by pattern (one parametrised test can implement two case variants);
that is allowed and visible.

Patterns know only two wildcards, ``*`` (any text) and ``?`` (one character). Everything else
is literal, including ``[`` and ``]``, which appear in real test names (pytest ids, TestNG
data-provider rows) and would be character classes in ``fnmatch``.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from functools import cache, lru_cache

from qualityintel.models.catalog import Catalog
from qualityintel.models.enums import AutomationStatus
from qualityintel.models.results import TestResult, TestRun


@dataclass(frozen=True)
class Execution:
    """One result together with the run it came from."""

    run: TestRun
    result: TestResult


@dataclass
class Matching:
    """Results grouped by test case, plus everything that did not fit.

    Attributes:
        by_case: Executions per test case id (every catalog case is a key, possibly empty).
        unmatched: Executions that belong to no test case (a test nobody mapped).
        unknown_ids: Explicit test ids found in results that are not in the catalog.
    """

    by_case: dict[str, list[Execution]]
    unmatched: list[Execution] = field(default_factory=list)
    unknown_ids: dict[str, int] = field(default_factory=dict)

    def automated_cases_without_results(self, catalog: Catalog) -> list[str]:
        """Automated case ids that no analysed result belongs to (renamed, deleted or not run)."""
        return [
            case.id
            for case in catalog.test_cases
            if case.automation_status is AutomationStatus.AUTOMATED and not self.by_case[case.id]
        ]


@cache
def compile_pattern(pattern: str) -> re.Pattern[str]:
    """Translate an ``automated_by`` pattern into a regular expression (``*``, ``?`` only)."""
    pieces = (
        ".*" if part == "*" else "." if part == "?" else re.escape(part)
        for part in re.split(r"([*?])", pattern)
    )
    return re.compile("".join(pieces), re.DOTALL)


def pattern_matches(pattern: str, key: str) -> bool:
    """True when the whole key matches the pattern (case-sensitive, like test names)."""
    return compile_pattern(pattern).fullmatch(key) is not None


def match_results(catalog: Catalog, runs: Iterable[TestRun]) -> Matching:
    """Assign every result of every run to test cases (see the module docstring for the rules)."""
    case_ids = {case.id for case in catalog.test_cases}
    patterns = tuple((case.id, tuple(case.automated_by)) for case in catalog.test_cases if case.automated_by)
    matching = Matching(by_case={case.id: [] for case in catalog.test_cases})
    # The same test runs in many runs: its key is matched against the patterns once
    by_key: dict[str, tuple[str, ...]] = {}

    for run in runs:
        for result in run.results:
            execution = Execution(run=run, result=result)
            targets: Sequence[str] = _explicit_targets(result, case_ids, matching)
            if not targets:
                if result.key not in by_key:
                    by_key[result.key] = _pattern_targets(result.key, patterns)
                targets = by_key[result.key]
            if not targets:
                matching.unmatched.append(execution)
            for case_id in targets:
                matching.by_case[case_id].append(execution)
    return matching


def _explicit_targets(result: TestResult, case_ids: set[str], matching: Matching) -> list[str]:
    """Case ids named by the result itself; unknown ids are counted for a warning."""
    targets: list[str] = []
    for test_id in result.test_ids:
        if test_id in case_ids:
            targets.append(test_id)
        else:
            matching.unknown_ids[test_id] = matching.unknown_ids.get(test_id, 0) + 1
    return targets


@lru_cache(maxsize=100_000)
def _pattern_targets(key: str, patterns: tuple[tuple[str, tuple[str, ...]], ...]) -> tuple[str, ...]:
    """Case ids with at least one pattern matching the key, in catalog order.

    Cached across calls (bounded): the answer depends only on the key and the catalog's
    patterns, which are both part of the cache key, so a changed catalog is matched afresh.
    """
    return tuple(
        case_id for case_id, case_patterns in patterns if any(pattern_matches(p, key) for p in case_patterns)
    )
