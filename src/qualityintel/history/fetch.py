"""Fetch a published history database and swap it in safely (docs/deployment.md).

The hosted dashboard has no disk that survives a restart: it fetches the history that the
collection workflow publishes, at start and then periodically. A fetched file replaces the
database only after it passed :meth:`HistoryStore.check`; until then the old file stays, and
the dashboard (which watches its sources) reloads once the new file is in place.

Only ``https`` addresses are accepted, the size is limited, and no credentials are sent: the
published history is public data by design (docs/operations.md, "Who can see it").
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any, Protocol

from qualityintel.history.store import HistoryError, HistoryStore

MAX_HISTORY_BYTES = 200 * 1024 * 1024
_CHUNK = 1024 * 1024
_TIMEOUT = 60


class Opener(Protocol):
    """What :func:`fetch_history` needs to open an address (tests pass a fake)."""

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        """Open ``request``; the result is a response usable as a context manager."""


class FetchError(RuntimeError):
    """The history could not be fetched, or the fetched file is not a usable history."""


@dataclass(frozen=True)
class Fetched:
    """Result of :func:`fetch_history`."""

    changed: bool
    runs: int
    results: int


def fetch_history(url: str, database: Path, opener: Opener | None = None) -> Fetched:
    """Download ``url`` and make it ``database`` if it is a valid history that differs.

    The ``ETag`` of the last fetched file is kept next to the database, so an unchanged
    publication is not downloaded again (``304 Not Modified``).

    Raises:
        FetchError: Not https, network or HTTP error, too large, or not a valid history; the
            existing database is left as it was.
    """
    if not url.startswith("https://"):
        raise FetchError("the history address must be an https:// address")
    tag_file = database.with_name(database.name + ".etag")
    request = urllib.request.Request(url, headers={"User-Agent": "qualityintel"})
    if database.is_file() and tag_file.is_file():
        request.add_header("If-None-Match", tag_file.read_text(encoding="utf-8").strip())
    database.parent.mkdir(parents=True, exist_ok=True)
    partial = database.with_name(database.name + ".download")
    try:
        with (opener or urllib.request.build_opener()).open(request, timeout=_TIMEOUT) as response:
            if not response.geturl().startswith("https://"):
                raise FetchError("the history address redirected to a non-https address")
            etag = response.headers.get("ETag")
            _save(response, partial)
    except urllib.error.HTTPError as error:
        if error.code == 304:
            with HistoryStore(database) as store:
                runs, results = store.count()
            return Fetched(changed=False, runs=runs, results=results)
        raise FetchError(f"HTTP {error.code} for the history address") from None
    except (urllib.error.URLError, TimeoutError, OSError) as error:
        partial.unlink(missing_ok=True)
        raise FetchError(f"cannot download the history: {getattr(error, 'reason', error)}") from None
    try:
        with HistoryStore(partial) as store:
            problems = store.check()
            runs, results = store.count()
    except HistoryError as error:
        partial.unlink(missing_ok=True)
        raise FetchError(f"the downloaded file is not a usable history ({error})") from None
    if problems:
        partial.unlink(missing_ok=True)
        raise FetchError(f"the downloaded history is damaged: {'; '.join(problems)}")
    os.replace(partial, database)  # one rename: readers see the old or the new file, never half
    if etag:
        tag_file.write_text(etag, encoding="utf-8")
    return Fetched(changed=True, runs=runs, results=results)


def _save(response: IO[bytes], target: Path) -> None:
    """Write the response body to ``target``, refusing anything above the size limit."""
    read = response.read
    written = 0
    with target.open("wb") as out:
        while chunk := read(_CHUNK):
            written += len(chunk)
            if written > MAX_HISTORY_BYTES:
                out.close()
                target.unlink(missing_ok=True)
                raise FetchError(f"the history is larger than {MAX_HISTORY_BYTES // (1024 * 1024)} MB")
            out.write(chunk)
