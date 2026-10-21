"""Performance regression guards on production-sized data (docs/performance.md).

The data: the 43 real sample runs, copied 12 times with later dates and new builds, so 516 runs
and 28,140 results, the size of the hosted history in October 2026 (250 runs, 29,898 results).

Two kinds of guard:

- **structural**: the number of pattern matches grows with the distinct tests, never with the
  number of runs (the N x M loop that made the live overview take 30 s must not come back);
  machine speed does not matter;
- **budgets**: time limits about four to five times what the views take on a developer laptop,
  so a slower CI machine passes and the code from before the fixes (overview about 2.6 s at this
  size) fails.
"""

import hashlib
import time
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import pytest

from qualityintel.ingest.batch import import_results
from qualityintel.ingest.catalog_file import load_catalog
from qualityintel.models.results import TestRun
from qualityintel.search import build_index, search
from qualityintel.traceability import matching
from qualityintel.workspace import Workspace

pytestmark = pytest.mark.performance

SAMPLES = Path(__file__).parents[2] / "samples"
COPIES = 12
# Seconds. Measured on the laptop (Python 3.13, 12 CPUs, best of 3, 2026-10-21): uncached overview
# 0.26, tests 0.12, stability 0.24, trends 0.57; warm-up 0.37 (before trends joined it); cached
# views 0.001 or less.
UNCACHED_BUDGET = {"overview": 1.2, "tests": 0.6, "stability": 1.0, "trends": 2.5}
WARM_BUDGET = 4.0
CACHED_BUDGET = 0.05


def copies(runs: list[TestRun], count: int) -> list[TestRun]:
    """``count`` copies of the runs, each a week later with its own build and run ids."""
    out: list[TestRun] = []
    for copy in range(count):
        for run in runs:
            out.append(
                run.model_copy(
                    update={
                        "run_id": hashlib.sha256(f"{run.run_id}-{copy}".encode()).hexdigest(),
                        "started_at": run.started_at + timedelta(days=7 * copy) if run.started_at else None,
                        "context": run.context.model_copy(update={"build": f"{run.context.build}-{copy}"}),
                    }
                )
            )
    return out


@pytest.fixture(scope="module")
def runs() -> list[TestRun]:
    """Production-sized history built from the real samples."""
    return copies(list(import_results([SAMPLES / "results"]).runs), COPIES)


def workspace(runs: list[TestRun]) -> Workspace:
    """A new workspace: nothing computed yet."""
    return Workspace(load_catalog(SAMPLES / "catalog.toml"), runs)


def seconds(action: Callable[[], object]) -> float:
    """Best of three: noise on a shared machine only ever adds time."""
    best = float("inf")
    for _ in range(3):
        start = time.perf_counter()
        action()
        best = min(best, time.perf_counter() - start)
    return best


def test_the_data_has_production_size(runs: list[TestRun]) -> None:
    """516 runs, 28,140 results."""
    assert (len(runs), sum(len(r.results) for r in runs)) == (516, 28_140)


def test_pattern_matching_grows_with_distinct_tests_not_with_runs(
    runs: list[TestRun], monkeypatch: pytest.MonkeyPatch
) -> None:
    """12 times the runs must not mean 12 times the pattern matches."""
    calls = 0
    original = matching.pattern_matches

    def counting(pattern: str, key: str) -> bool:
        nonlocal calls
        calls += 1
        return original(pattern, key)

    monkeypatch.setattr(matching, "pattern_matches", counting)
    catalog = load_catalog(SAMPLES / "catalog.toml")
    one_copy = runs[: len(runs) // COPIES]

    matching._pattern_targets.cache_clear()
    matching.match_results(catalog, one_copy)
    once = calls
    calls = 0
    matching._pattern_targets.cache_clear()
    matching.match_results(catalog, runs)

    assert once > 0
    assert calls == once  # the same distinct keys: the same work, whatever the number of runs


@pytest.mark.parametrize("view", sorted(UNCACHED_BUDGET))
def test_uncached_views_stay_within_budget(runs: list[TestRun], view: str) -> None:
    """The first request of a view on a new snapshot (what the warm-up pays once)."""
    actions: dict[str, Callable[[Workspace], object]] = {
        "overview": lambda w: (w.summary(), w.readiness()),
        "tests": lambda w: w.tests(),
        "stability": lambda w: w.stability(),
        "trends": lambda w: w.trends(),
    }

    took = seconds(lambda: actions[view](workspace(runs)))

    assert took < UNCACHED_BUDGET[view], f"{view}: {took:.2f} s, budget {UNCACHED_BUDGET[view]} s"


def test_after_the_warm_up_every_default_view_is_immediate(runs: list[TestRun]) -> None:
    """Warm-up within budget; then overview, tests and stability answer from the cache."""
    ready = workspace(runs)
    start = time.perf_counter()
    ready.warm()
    warm = time.perf_counter() - start

    assert warm < WARM_BUDGET, f"warm-up {warm:.2f} s, budget {WARM_BUDGET} s"
    cached: dict[str, Callable[[], object]] = {
        "summary": ready.summary,
        "tests": ready.tests,
        "stability": ready.stability,
        "trends": ready.trends,
    }
    for name, view in cached.items():
        took = seconds(view)
        assert took < CACHED_BUDGET, f"{name} after warm-up: {took:.3f} s, budget {CACHED_BUDGET} s"


# Measured the same way (2026-10-21): search index 0.063 s (267 entries; 0.07 s for the 2,095 entries
# of the hosted history), a query about 0.2 ms, Needs Attention 0.35 s uncached and under 1 ms cached.
SEARCH_INDEX_BUDGET = 0.5
SEARCH_QUERY_BUDGET = 0.05
ATTENTION_BUDGET = 2.0


def test_search_builds_its_index_once_and_answers_within_budget(runs: list[TestRun]) -> None:
    """The index per snapshot, then a query that only filters it."""
    ready = workspace(runs)
    took = seconds(lambda: build_index(ready.catalog, ready.runs, ready.collections))
    index = build_index(ready.catalog, ready.runs, ready.collections)

    assert took < SEARCH_INDEX_BUDGET, f"index {took:.2f} s, budget {SEARCH_INDEX_BUDGET} s"
    for query in ("checkout", "admin customer", "SHOP-006"):
        answered = seconds(lambda q=query: search(index, q))  # type: ignore[misc]
        assert answered < SEARCH_QUERY_BUDGET, f"{query!r}: {answered * 1000:.1f} ms"


def test_needs_attention_stays_within_budget_and_is_warm_after_the_warm_up(runs: list[TestRun]) -> None:
    """Uncached within budget; after the warm-up, the page and a search answer from the cache."""
    took = seconds(lambda: workspace(runs).attention())
    assert took < ATTENTION_BUDGET, f"attention {took:.2f} s, budget {ATTENTION_BUDGET} s"

    ready = workspace(runs)
    ready.warm()
    assert seconds(ready.attention) < CACHED_BUDGET
    assert seconds(lambda: ready.search("checkout")) < CACHED_BUDGET
