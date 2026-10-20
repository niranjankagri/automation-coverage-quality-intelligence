"""Dashboard data that follows its sources: reload when history or catalog change (docs/dashboard.md).

A :class:`Snapshot` is one immutable, fully built :class:`~qualityintel.workspace.Workspace`
with the version of the sources it was built from. :class:`LiveData` holds the current one and
replaces it only with another complete snapshot, so a request never sees half-updated data:

- the sources (catalog and its includes, history database, result files) are fingerprinted by
  size and modification time; a check rebuilds only when the fingerprint changed;
- one reload at a time; a check while another one runs returns at once;
- a failed reload (a locked or corrupted database, a broken catalog) keeps the previous
  snapshot and records the error, which the dashboard shows as stale data;
- a forced check (the Refresh control) is limited to one every ``MIN_FORCED_SECONDS``.

No web framework is imported here (architecture rule): the dashboard only calls these methods.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from qualityintel.gates.config import GateConfigError, load_gate_config
from qualityintel.history.store import HistoryError, HistoryStore
from qualityintel.ingest.batch import expand_inputs, import_results
from qualityintel.ingest.catalog_file import CatalogFileError, load_catalog, read_toml
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.results import RunContext, TestRun
from qualityintel.workspace import Workspace

MIN_FORCED_SECONDS = 5.0


class LoadError(RuntimeError):
    """The dashboard data could not be built from its sources."""


@dataclass(frozen=True)
class Snapshot:
    """One complete build of the dashboard data.

    Attributes:
        version: Short hash of the sources' fingerprint; changes when any source changes.
        loaded_at: When this snapshot was built.
        sources_modified_at: Latest modification time among the sources.
    """

    workspace: Workspace
    version: str
    loaded_at: datetime
    sources_modified_at: datetime | None = None
    collections: tuple[PipelineCollection, ...] = ()


@dataclass(frozen=True)
class Status:
    """What the dashboard shows about its data."""

    version: str
    loaded_at: datetime
    sources_modified_at: datetime | None
    interval_seconds: float
    last_check: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    stale: bool


@dataclass(frozen=True)
class Sources:
    """The files a snapshot is built from."""

    catalog: Path
    database: Path | None = None
    results: tuple[str | Path, ...] = ()
    context: RunContext | None = None
    gate: Path | None = None

    def files(self) -> list[Path]:
        """Every file whose change must reload the data (catalog includes and result files too)."""
        files = [self.catalog]
        try:
            includes = read_toml(self.catalog).get("include", [])
            files += [self.catalog.parent / name for name in includes if isinstance(name, str)]
        except CatalogFileError:
            pass  # the load reports it
        if self.database is not None:
            files.append(self.database)
        if self.gate is not None:
            files.append(self.gate)
        if self.results:
            found, _ = expand_inputs(self.results)
            files += [path for path, _name in found]
        return files

    def fingerprint(self) -> tuple[str, datetime | None]:
        """``(version, latest modification)`` of the sources; missing files count as missing."""
        digest = hashlib.sha256()
        latest = 0
        for path in self.files():
            try:
                stat = path.stat()
            except OSError:
                digest.update(f"{path}:missing\n".encode())
                continue
            digest.update(f"{path}:{stat.st_size}:{stat.st_mtime_ns}\n".encode())
            latest = max(latest, stat.st_mtime_ns)
        modified = datetime.fromtimestamp(latest / 1e9, tz=UTC) if latest else None
        return digest.hexdigest()[:12], modified


def load_snapshot(sources: Sources) -> Snapshot:
    """Build a snapshot from the sources.

    Raises:
        LoadError: The catalog or database cannot be read, or a result file is broken.
    """
    version, modified = sources.fingerprint()
    try:
        catalog = load_catalog(sources.catalog)
    except CatalogFileError as error:
        raise LoadError(str(error)) from None
    try:
        gate = load_gate_config(sources.gate) if sources.gate is not None else None
    except GateConfigError as error:
        raise LoadError(str(error)) from None
    runs: list[TestRun] = []
    snapshots = []
    collections: list[PipelineCollection] = []
    if sources.database is not None:
        try:
            with HistoryStore(sources.database) as store:
                runs = store.runs()
                snapshots = store.snapshots()
                collections = store.collections()
        except HistoryError as error:
            raise LoadError(str(error)) from None
        except sqlite3.Error as error:  # e.g. locked while a collection writes
            raise LoadError(f"{sources.database.name}: cannot be read ({error})") from None
    if sources.results:
        batch = import_results(sources.results, context=sources.context)
        if not batch.complete:
            reasons = "; ".join(str(e) for e in batch.errors) or "no results"
            raise LoadError(f"result files: {reasons}")
        known = {run.run_id for run in runs}
        runs += [run for run in batch.runs if run.run_id not in known]
    return Snapshot(
        workspace=Workspace(catalog, runs, snapshots, collections, gate),
        version=version,
        loaded_at=datetime.now(UTC),
        sources_modified_at=modified,
        collections=tuple(collections),
    )


@dataclass
class LiveData:
    """The current snapshot, reloaded when its sources change.

    Args:
        snapshot: The first snapshot (load it before starting the server, so a broken source
            is an error at start-up, not a stale dashboard).
        sources: Where to reload from; ``None`` for fixed data (tests, file inputs only).
        interval_seconds: Seconds between automatic checks; 0 turns them off.
    """

    snapshot: Snapshot
    sources: Sources | None = None
    interval_seconds: float = 0.0
    loader: Callable[[Sources], Snapshot] = load_snapshot
    clock: Callable[[], float] = time.monotonic
    last_check: datetime | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _last_forced: float = field(default=-1e9, repr=False)
    _stop: threading.Event = field(default_factory=threading.Event, repr=False)
    _thread: threading.Thread | None = field(default=None, repr=False)

    @classmethod
    def fixed(cls, workspace: Workspace) -> LiveData:
        """Data that never changes (the version is constant)."""
        return cls(
            Snapshot(
                workspace=workspace,
                version="fixed",
                loaded_at=datetime.now(UTC),
                collections=tuple(workspace.collections),
            )
        )

    def current(self) -> Snapshot:
        """The snapshot to answer one request with (never a half-built one)."""
        return self.snapshot

    def check(self, force: bool = False) -> bool:
        """Reload if the sources changed; ``True`` when a new snapshot is now current.

        A forced check within ``MIN_FORCED_SECONDS`` of the previous one does nothing, and so
        does any check while another reload is running.
        """
        if self.sources is None:
            return False
        if force:
            now = self.clock()
            if now - self._last_forced < MIN_FORCED_SECONDS:
                return False
            self._last_forced = now
        if not self._lock.acquire(blocking=False):
            return False
        try:
            self.last_check = datetime.now(UTC)
            try:
                version, _ = self.sources.fingerprint()
                if version == self.snapshot.version and self.last_error is None:
                    return False
                fresh = self.loader(self.sources)
            except (LoadError, OSError) as error:
                self.last_error = str(error)
                self.last_error_at = self.last_check
                return False
            self.snapshot = fresh  # one assignment: requests see the old or the new, never a mix
            self.last_error = None
            self.last_error_at = None
            return True
        finally:
            self._lock.release()

    def status(self) -> Status:
        """Freshness, the last error, and whether the data shown is known to be outdated."""
        stale = self.last_error is not None
        return Status(
            version=self.snapshot.version,
            loaded_at=self.snapshot.loaded_at,
            sources_modified_at=self.snapshot.sources_modified_at,
            interval_seconds=self.interval_seconds,
            last_check=self.last_check,
            last_error=self.last_error,
            last_error_at=self.last_error_at,
            stale=stale,
        )

    def start(self) -> None:
        """Check every ``interval_seconds`` in a background thread (nothing when 0 or fixed)."""
        if self.interval_seconds <= 0 or self.sources is None or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="qi-refresh", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the background checks."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.wait(self.interval_seconds):
            self.check()
