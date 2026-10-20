"""LiveData: reload on change, keep the last good snapshot on failure, one reload at a time."""

import os
import shutil
import sqlite3
import time
from contextlib import closing
from pathlib import Path

import pytest

from qualityintel.history.store import HistoryStore
from qualityintel.live import MIN_FORCED_SECONDS, LiveData, LoadError, Sources, load_snapshot

from .traceability.helpers import result, run

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[2] / "samples"


@pytest.fixture
def sources(tmp_path: Path) -> Sources:
    """The sample catalog (with its include) and a history database with one run."""
    for name in ("catalog.toml", "requirements.toml"):
        shutil.copy(SAMPLES / name, tmp_path / name)
    with HistoryStore(tmp_path / "h.db") as store:
        store.add(run(result("A"), day=18))
    return Sources(tmp_path / "catalog.toml", tmp_path / "h.db")


def add_run(sources: Sources, day: int) -> None:
    """Store another run (what a collection or an import does)."""
    assert sources.database is not None
    with HistoryStore(sources.database) as store:
        store.add(run(result("B"), day=day))
    bump(sources.database)


def bump(path: Path) -> None:
    """Make sure the modification time moves on file systems with coarse timestamps."""
    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))


def test_unchanged_sources_are_not_reloaded_and_new_data_is(sources: Sources) -> None:
    """A check without changes returns False; after a new run it swaps in a new snapshot."""
    live = LiveData(load_snapshot(sources), sources, interval_seconds=30)
    first = live.current()

    assert live.check() is False
    assert live.current() is first
    add_run(sources, day=19)
    assert live.check() is True
    assert live.current().version != first.version
    assert len(live.current().workspace.runs) == len(first.workspace.runs) + 1


def test_catalog_includes_are_watched_too(sources: Sources) -> None:
    """Changing requirements.toml (included by the catalog) is a change of the data."""
    live = LiveData(load_snapshot(sources), sources)
    included = sources.catalog.parent / "requirements.toml"
    included.write_text(included.read_text(encoding="utf-8") + "\n", encoding="utf-8")
    bump(included)

    assert live.check() is True


def test_a_failed_reload_keeps_the_last_good_data_and_says_so(sources: Sources) -> None:
    """A broken catalog: the previous snapshot stays, the status is stale with the reason."""
    live = LiveData(load_snapshot(sources), sources)
    good = live.current()
    sources.catalog.write_text("[[requirement]\n", encoding="utf-8")
    bump(sources.catalog)

    assert live.check() is False
    assert live.current() is good
    status = live.status()
    assert status.stale
    assert status.last_error is not None
    assert "not valid TOML" in status.last_error

    shutil.copy(SAMPLES / "catalog.toml", sources.catalog)  # fixed: the next check recovers
    bump(sources.catalog)
    assert live.check() is True
    assert not live.status().stale


def test_a_locked_or_corrupted_database_is_a_load_error(sources: Sources) -> None:
    """While another process holds a write lock, or when the file is garbage: no crash, an error."""
    assert sources.database is not None
    with closing(sqlite3.connect(sources.database, timeout=0)) as other:
        other.execute("BEGIN EXCLUSIVE")
        with pytest.raises(LoadError, match=r"locked|cannot be"):
            load_snapshot(sources)
        other.rollback()

    sources.database.write_bytes(b"not a database" * 100)
    with pytest.raises(LoadError, match="cannot be used as a history database"):
        load_snapshot(sources)


def test_an_empty_database_is_valid_data(tmp_path: Path, sources: Sources) -> None:
    """A fresh database: a snapshot without runs, not an error."""
    empty = Sources(sources.catalog, tmp_path / "empty.db")

    assert load_snapshot(empty).workspace.runs == ()


def test_forced_checks_are_rate_limited(sources: Sources) -> None:
    """The Refresh control cannot make the server reload in a loop."""
    now = [1000.0]
    calls = []

    def loader(src: Sources) -> object:
        calls.append(1)
        return load_snapshot(src)

    live = LiveData(load_snapshot(sources), sources, loader=loader, clock=lambda: now[0])  # type: ignore[arg-type]
    add_run(sources, day=19)
    assert live.check(force=True) is True
    add_run(sources, day=20)
    assert live.check(force=True) is False  # too soon
    now[0] += MIN_FORCED_SECONDS + 1
    assert live.check(force=True) is True
    assert len(calls) == 2


def test_a_check_during_a_reload_returns_at_once(sources: Sources) -> None:
    """Only one reload runs; a second check does not wait for it or start another."""
    live = LiveData(load_snapshot(sources), sources)
    add_run(sources, day=19)
    live._lock.acquire()
    try:
        assert live.check() is False
    finally:
        live._lock.release()
    assert live.check() is True


def test_the_background_thread_picks_up_new_data(sources: Sources) -> None:
    """With an interval, new data appears without anyone asking."""
    live = LiveData(load_snapshot(sources), sources, interval_seconds=0.05)
    first = live.current()
    live.start()
    try:
        add_run(sources, day=19)
        deadline = time.monotonic() + 5
        while live.current() is first and time.monotonic() < deadline:
            time.sleep(0.02)
    finally:
        live.stop()

    assert live.current() is not first


def test_fixed_data_never_reloads(sources: Sources) -> None:
    """Without sources there is nothing to watch."""
    live = LiveData.fixed(load_snapshot(sources).workspace)

    assert live.check(force=True) is False
    assert live.status().version == "fixed"
    live.start()  # no thread for fixed data
    live.stop()
