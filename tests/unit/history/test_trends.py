import sqlite3
from contextlib import closing
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from qualityintel.history.store import SCHEMA_VERSION, HistoryStore
from qualityintel.history.trends import coverage_changes, coverage_snapshot, daily_trend
from qualityintel.models.catalog import Catalog
from qualityintel.models.enums import Outcome
from qualityintel.models.metrics import Ratio
from qualityintel.traceability.report import RunFilters

from ..traceability.helpers import case, catalog, req, result, run

pytestmark = pytest.mark.unit

P, F, S = Outcome.PASSED, Outcome.FAILED, Outcome.SKIPPED


@pytest.fixture
def shop() -> Catalog:
    """R1 tested by A (firefox and chrome runs), R2 tested by B (firefox only)."""
    return catalog([req("R1"), req("R2")], [case("A", "R1"), case("B", "R2")])


def test_one_point_per_day_with_the_snapshot_at_the_end_of_that_day(shop: Catalog) -> None:
    """Day 1: firefox fails B. Day 2: chrome runs; firefox is carried over from day 1."""
    runs = [
        run(
            result("A", duration_seconds=1.0), result("B", F, duration_seconds=2.0), day=1, browser="firefox"
        ),
        run(result("A", duration_seconds=3.0), day=2, browser="chrome"),
    ]

    points = daily_trend(runs, shop)

    assert [p.day for p in points] == [date(2026, 10, 1), date(2026, 10, 2)]
    assert points[0].counts[F] == 1
    assert points[0].pass_rate == Ratio(numerator=1, denominator=2)
    assert points[0].carried == ()
    # day 2 snapshot = firefox (day 1) + chrome (day 2): 2 passed, 1 failed
    assert points[1].pass_rate == Ratio(numerator=2, denominator=3)
    assert points[1].duration_seconds == 6.0
    assert points[1].contexts == 2
    assert points[1].carried == ("-/-/firefox/-",)
    assert points[1].requirement_status == {"passing": 1, "failing": 1}


def test_a_newer_run_of_the_same_context_replaces_the_older_one(shop: Catalog) -> None:
    """Day 2 firefox replaces day 1 firefox: nothing carried, B passing now."""
    runs = [
        run(result("A"), result("B", F), day=1, browser="firefox"),
        run(result("A"), result("B"), day=2, browser="firefox"),
    ]

    points = daily_trend(runs, shop)

    assert points[1].carried == ()
    assert points[1].requirement_status == {"passing": 2}


def test_undated_runs_and_empty_input_give_no_points(shop: Catalog) -> None:
    """Without dates there is no time axis: no invented points."""
    assert daily_trend([run(result("A"), day=None)], shop) == []
    assert daily_trend([], shop) == []


def test_skips_count_separately_from_the_pass_rate(shop: Catalog) -> None:
    """Skipped results are in the counts, not in the pass rate."""
    points = daily_trend([run(result("A"), result("B", S), day=3)], shop)

    assert points[0].counts[S] == 1
    assert points[0].pass_rate == Ratio(numerator=1, denominator=1)


def test_run_filters_on_build_and_dates() -> None:
    """Build and inclusive date range select runs; undated runs drop out once dates are set."""
    first, second = run(result("A"), day=1, build="1.0"), run(result("A"), day=5, build="1.1")
    undated = run(result("A"), day=None, build="1.1")

    assert RunFilters(builds=frozenset({"1.1"})).keeps(second)
    assert not RunFilters(builds=frozenset({"1.1"})).keeps(first)
    assert RunFilters(since=date(2026, 10, 5)).keeps(second)
    assert not RunFilters(since=date(2026, 10, 2)).keeps(first)
    assert RunFilters(until=date(2026, 10, 1)).keeps(first)
    assert not RunFilters(until=date(2026, 10, 4)).keeps(second)
    assert not RunFilters(since=date(2026, 1, 1)).keeps(undated)
    assert RunFilters().keeps(undated)


def test_coverage_snapshot_hash_ignores_formatting_but_sees_content(shop: Catalog) -> None:
    """Same catalog = same hash; a new requirement = new hash and new numbers."""
    same = coverage_snapshot(catalog([req("R1"), req("R2")], [case("A", "R1"), case("B", "R2")]), "c.toml")
    first = coverage_snapshot(shop, "c.toml")
    bigger = coverage_snapshot(
        catalog([req("R1"), req("R2"), req("R3")], [case("A", "R1"), case("B", "R2")]), "c.toml"
    )

    assert first.catalog_sha256 == same.catalog_sha256
    assert bigger.catalog_sha256 != first.catalog_sha256
    assert (first.requirement_coverage, bigger.requirement_coverage) == (
        Ratio(numerator=2, denominator=2),
        Ratio(numerator=2, denominator=3),
    )


def test_store_keeps_snapshots_only_when_the_catalog_changed(tmp_path: Path, shop: Catalog) -> None:
    """Recording an unchanged catalog again adds nothing; a change adds a point."""
    early = coverage_snapshot(shop, "c.toml", datetime(2026, 10, 1, tzinfo=UTC))
    again = coverage_snapshot(shop, "c.toml", datetime(2026, 10, 2, tzinfo=UTC))
    changed = coverage_snapshot(
        catalog([req("R1"), req("R2"), req("R3")], []), "c.toml", datetime(2026, 10, 3, tzinfo=UTC)
    )

    with HistoryStore(tmp_path / "h.db") as store:
        assert store.add_snapshot(early) is True
        assert store.add_snapshot(again) is False
        assert store.add_snapshot(changed) is True
        stored = store.snapshots()

    assert stored == [early, changed]


def test_coverage_notes_explain_short_series(shop: Catalog) -> None:
    """Zero or one snapshot is said plainly, never drawn as a trend."""
    one = coverage_snapshot(shop, "c.toml")

    assert "no coverage snapshot recorded yet" in coverage_changes([])[0]
    assert "one coverage snapshot so far" in coverage_changes([one])[0]
    assert coverage_changes([one, one]) == []


def test_version_1_database_is_upgraded_without_losing_runs(tmp_path: Path) -> None:
    """A history file written before snapshots existed opens, keeps its runs and gains the table."""
    path = tmp_path / "old.db"
    with HistoryStore(path) as store:
        store.add(run(result("A"), day=1))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute("DROP TABLE coverage_snapshots")
        db.execute("UPDATE schema_version SET version = 1")

    with HistoryStore(path) as store:
        assert store.count() == (1, 1)
        assert store.snapshots() == []
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT version FROM schema_version").fetchone()[0] == SCHEMA_VERSION
