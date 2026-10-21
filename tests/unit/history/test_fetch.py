"""Fetching a published history: verified before it replaces anything (docs/deployment.md)."""

import io
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from qualityintel.history.fetch import FetchError, fetch_history
from qualityintel.history.store import HistoryStore
from qualityintel.ingest.batch import import_results

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[3] / "samples" / "results"
URL = "https://github.com/owner/repo/releases/download/history/quality.db"


class Response(io.BytesIO):
    """A response body with the headers and final address urllib would give."""

    def __init__(self, body: bytes, etag: str | None = None, final_url: str = URL) -> None:
        super().__init__(body)
        self.headers = Message()
        if etag:
            self.headers["ETag"] = etag
        self.final_url = final_url

    def geturl(self) -> str:
        """The address after redirects."""
        return self.final_url


class Opener:
    """Answers every request with the next prepared answer and remembers the requests."""

    def __init__(self, *answers: Response | urllib.error.HTTPError | OSError) -> None:
        self.answers = list(answers)
        self.requests: list[urllib.request.Request] = []

    def open(self, request: urllib.request.Request, timeout: float) -> Any:
        """Next answer, or raise it."""
        self.requests.append(request)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer


def history_bytes(tmp_path: Path, name: str = "published.db") -> bytes:
    """A real history database with the 43 sample runs, as published."""
    path = tmp_path / name
    with HistoryStore(path) as store:
        store.add_all(import_results([SAMPLES]).runs)
    return path.read_bytes()


def not_modified() -> urllib.error.HTTPError:
    """The answer to a conditional request for an unchanged file."""
    return urllib.error.HTTPError(URL, 304, "Not Modified", Message(), None)


def test_a_valid_history_replaces_the_database_and_is_not_fetched_twice(tmp_path: Path) -> None:
    """First fetch swaps the file in; the next one asks with the ETag and keeps the file on 304."""
    database = tmp_path / "data" / "quality.db"
    opener = Opener(Response(history_bytes(tmp_path), etag='"v1"'), not_modified())

    first = fetch_history(URL, database, opener)
    second = fetch_history(URL, database, opener)

    assert (first.changed, first.runs) == (True, 43)
    assert (second.changed, second.runs) == (False, 43)
    assert opener.requests[1].get_header("If-none-match") == '"v1"'
    assert not database.with_name("quality.db.download").exists()


@pytest.mark.parametrize(
    ("answer", "message"),
    [
        (Response(b"<html>not a database</html>" * 50), "not a usable history"),
        (urllib.error.HTTPError(URL, 404, "Not Found", Message(), None), "HTTP 404"),
        (urllib.error.URLError("name resolution failed"), "cannot download"),
        (Response(b"x", final_url="http://example.com/quality.db"), "non-https"),
    ],
    ids=["not-a-database", "missing", "network", "redirect-to-http"],
)
def test_a_failed_fetch_leaves_the_existing_database_alone(
    tmp_path: Path, answer: Response | OSError, message: str
) -> None:
    """Whatever goes wrong, the dashboard keeps the history it has."""
    database = tmp_path / "quality.db"
    database.write_bytes(history_bytes(tmp_path))
    before = database.read_bytes()

    with pytest.raises(FetchError, match=message):
        fetch_history(URL, database, Opener(answer))

    assert database.read_bytes() == before
    assert not database.with_name("quality.db.download").exists()


def test_only_https_addresses_are_fetched(tmp_path: Path) -> None:
    """A plain http address is refused before any request."""
    opener = Opener()

    with pytest.raises(FetchError, match="https"):
        fetch_history("http://example.com/quality.db", tmp_path / "quality.db", opener)
    assert opener.requests == []


def test_a_file_above_the_size_limit_is_refused(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The limit is checked while reading, so a huge answer never fills the disk."""
    monkeypatch.setattr("qualityintel.history.fetch.MAX_HISTORY_BYTES", 1000)

    with pytest.raises(FetchError, match="larger than"):
        fetch_history(URL, tmp_path / "quality.db", Opener(Response(b"0" * 5000)))
    assert not (tmp_path / "quality.db").exists()


@pytest.mark.parametrize("fraction", [0.5, 0.9, 0.999])
def test_a_truncated_download_never_replaces_the_database(tmp_path: Path, fraction: float) -> None:
    """A real history cut short (interrupted transfer) is refused; the old file stays."""
    database = tmp_path / "quality.db"
    published = history_bytes(tmp_path)
    database.write_bytes(published)

    with pytest.raises(FetchError, match=r"not a usable history|damaged") as refused:
        fetch_history(URL, database, Opener(Response(published[: int(len(published) * fraction)])))

    assert len(str(refused.value)) < 1000  # a damaged file is described briefly, not row by row
    assert database.read_bytes() == published
