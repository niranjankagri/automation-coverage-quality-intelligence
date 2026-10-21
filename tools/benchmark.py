"""Benchmark the dashboard's analyses on a history database (docs/performance.md).

Usage: ``python tools/benchmark.py DATABASE [--catalog FILE] [--gate FILE] [--rounds N] [--json OUT]``

Measures, in this process (no HTTP): building the snapshot from the database (cold), the
warm-up that runs before a snapshot goes live, and every major view twice: **uncached** (a new
workspace, nothing computed yet: what a request costs without the cache) and **cached** (the
second request of the same view). Also the peak memory of building and warming a snapshot
(``tracemalloc``: Python allocations, not the whole process). Each figure is the median of
``--rounds`` repetitions. The environment (Python, platform, CPU count) is printed with the
numbers, because timings only compare on the same machine.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import sys
import time
import tracemalloc
from collections.abc import Callable
from pathlib import Path
from typing import Any

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "src"))

from qualityintel.live import Sources, load_snapshot  # noqa: E402
from qualityintel.workspace import Workspace  # noqa: E402


def timed(action: Callable[[], object]) -> float:
    """Seconds one call takes."""
    start = time.perf_counter()
    action()
    return time.perf_counter() - start


def views(workspace: Workspace) -> dict[str, Callable[[], object]]:
    """The dashboard's major views, as the API asks for them without filters."""
    return {
        "overview (summary + readiness)": lambda: (workspace.summary(), workspace.readiness()),
        "requirements": lambda: (workspace.requirements(), workspace.requirement_matrix()),
        "tests": workspace.tests,
        "pipelines": workspace.pipelines,
        "trends": workspace.trends,
        "stability": workspace.stability,
    }


def benchmark(database: Path, catalog: Path, gate: Path | None, rounds: int) -> dict[str, Any]:
    """All measurements as a dictionary (seconds, bytes)."""
    sources = Sources(catalog, database, (), None, gate)
    load: list[float] = []
    warm: list[float] = []
    uncached: dict[str, list[float]] = {}
    cached: dict[str, list[float]] = {}
    for _ in range(rounds):
        start = time.perf_counter()
        snapshot = load_snapshot(sources)
        load.append(time.perf_counter() - start)
        base = snapshot.workspace
        for name in views(base):
            # A workspace of its own per view: nothing computed by another view is reused
            workspace = Workspace(base.catalog, base.runs, base.snapshots, base.collections, base.gate)
            view = views(workspace)[name]
            uncached.setdefault(name, []).append(timed(view))
            cached.setdefault(name, []).append(timed(view))
        fresh = Workspace(base.catalog, base.runs, base.snapshots, base.collections, base.gate)
        warm.append(timed(fresh.warm) if hasattr(fresh, "warm") else float("nan"))
    tracemalloc.start()
    built = load_snapshot(sources).workspace
    if hasattr(built, "warm"):
        built.warm()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    runs = base.runs
    return {
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "cpus": os.cpu_count(),
        },
        "data": {"runs": len(runs), "results": sum(len(r.results) for r in runs)},
        "load_snapshot_s": statistics.median(load),
        "warm_s": statistics.median(warm),
        "uncached_s": {name: statistics.median(times) for name, times in uncached.items()},
        "cached_s": {name: statistics.median(times) for name, times in cached.items()},
        "peak_memory_mb": round(peak / 1024 / 1024, 1),
    }


def main(argv: list[str] | None = None) -> int:
    """Run the benchmark and print a table (and JSON when asked)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("database", type=Path)
    parser.add_argument("--catalog", type=Path, default=ROOT / "samples" / "catalog.toml")
    parser.add_argument("--gate", type=Path, default=ROOT / "samples" / "gates" / "nightly.toml")
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--json", type=Path, help="also write the numbers as JSON")
    args = parser.parse_args(argv)
    numbers = benchmark(args.database, args.catalog, args.gate, args.rounds)
    env, data = numbers["environment"], numbers["data"]
    print(f"{data['runs']} runs, {data['results']} results")
    print(f"Python {env['python']}, {env['cpus']} CPUs, {env['platform']}")
    print(f"load snapshot  {numbers['load_snapshot_s']:.3f} s   warm-up {numbers['warm_s']:.3f} s")
    print(f"peak memory    {numbers['peak_memory_mb']} MB (build and warm a snapshot)")
    print(f"{'view':<32} {'uncached':>10} {'cached':>10}")
    for name, seconds in numbers["uncached_s"].items():
        print(f"{name:<32} {seconds:>9.3f}s {numbers['cached_s'][name]:>9.4f}s")
    if args.json:
        args.json.write_text(json.dumps(numbers, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
