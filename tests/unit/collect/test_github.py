"""The GitHub client against a fake opener: requests, redirects, errors, limits."""

import io
import json
import urllib.error
import urllib.request
from datetime import UTC, datetime
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from qualityintel.collect import github
from qualityintel.collect.github import Artifact, CollectError, GitHubActions

pytestmark = pytest.mark.unit

TOKEN = "ghs_secret_token_value"


class Response(io.BytesIO):
    """A urllib response: readable bytes, usable as a context manager."""


def http_error(url: str, code: int, location: str | None = None) -> urllib.error.HTTPError:
    """An HTTPError like urllib raises it."""
    headers = Message()
    if location:
        headers["Location"] = location
    return urllib.error.HTTPError(url, code, "error", headers, None)


class Opener:
    """Records requests; answers from a list of (url prefix, answer) pairs."""

    def __init__(self, answers: list[tuple[str, Any]]) -> None:
        self.answers = answers
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request) -> Response:
        """Answer the first matching prefix; an exception answer is raised."""
        self.requests.append(request)
        for prefix, answer in self.answers:
            if request.full_url.startswith(prefix):
                if isinstance(answer, BaseException):
                    raise answer
                return Response(answer if isinstance(answer, bytes) else json.dumps(answer).encode())
        raise AssertionError(f"unexpected request {request.full_url}")


RUN = {
    "id": 39403545716,
    "run_attempt": 2,
    "run_number": 61,
    "event": "schedule",
    "head_branch": "main",
    "head_sha": "fbb6ebe1234567890",
    "conclusion": "cancelled",
    "html_url": "https://github.com/o/r/actions/runs/39403545716",
    "run_started_at": "2026-10-20T09:00:00Z",
}


def test_runs_are_listed_with_attempt_branch_commit_and_conclusion() -> None:
    """The query asks for completed runs of the branch since the date; fields are mapped."""
    opener = Opener(
        [("https://api.github.com/repos/o/r/actions/workflows/ci.yml/runs", {"workflow_runs": [RUN]})]
    )

    (run,) = GitHubActions(TOKEN, opener=opener).completed_runs(
        "o/r", "ci.yml", "main", datetime(2026, 10, 18, tzinfo=UTC)
    )

    url = opener.requests[0].full_url
    assert "status=completed" in url
    assert "branch=main" in url
    assert "created=%3E%3D2026-10-18" in url
    assert (run.id, run.attempt, run.commit, run.conclusion) == (39403545716, 2, "fbb6ebe12345", "cancelled")
    assert run.started_at == datetime(2026, 10, 20, 9, tzinfo=UTC)


def test_the_token_goes_to_the_api_but_not_to_the_storage_redirect(tmp_path: Path) -> None:
    """GitHub answers the download with a redirect to signed storage: no Authorization there."""
    storage = "https://productionresults.blob.core.windows.net/a.zip?sig=x"
    opener = Opener(
        [
            ("https://api.github.com/repos/o/r/actions/artifacts/5/zip", http_error("u", 302, storage)),
            ("https://productionresults", b"PK-zip-bytes"),
        ]
    )

    GitHubActions(TOKEN, opener=opener).download("o/r", Artifact(5, "report", 12, False), tmp_path / "a.zip")

    api_request, storage_request = opener.requests
    assert api_request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert storage_request.get_header("Authorization") is None
    assert (tmp_path / "a.zip").read_bytes() == b"PK-zip-bytes"


@pytest.mark.parametrize(
    ("code", "transient"), [(401, True), (403, True), (429, True), (502, True), (404, False), (410, False)]
)
def test_http_errors_say_whether_to_retry_and_never_show_the_token(code: int, transient: bool) -> None:
    """Token, rate-limit and server problems are retried; a missing object belongs to the run."""
    opener = Opener([("https://api.github.com", http_error("u", code))])

    with pytest.raises(CollectError) as raised:
        GitHubActions(TOKEN, opener=opener).artifacts("o/r", 1)

    assert raised.value.transient is transient
    assert f"HTTP {code}" in str(raised.value)
    assert TOKEN not in str(raised.value)


def test_network_errors_are_transient() -> None:
    """No answer at all: try again later."""
    opener = Opener([("https://api.github.com", urllib.error.URLError("timed out"))])

    with pytest.raises(CollectError, match="timed out") as raised:
        GitHubActions(TOKEN, opener=opener).artifacts("o/r", 1)
    assert raised.value.transient


def test_downloads_need_a_token_and_respect_the_size_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without a token nothing is requested; a too-large artifact is refused before and while reading."""
    opener = Opener([("https://api.github.com", b"x" * 100)])
    with pytest.raises(CollectError, match="needs a token") as raised:
        GitHubActions(None, opener=opener).download("o/r", Artifact(1, "a", 10, False), tmp_path / "a.zip")
    assert raised.value.transient
    assert opener.requests == []

    monkeypatch.setattr(github, "MAX_ARTIFACT_BYTES", 50)
    with pytest.raises(CollectError, match="more than 50"):
        GitHubActions(TOKEN, opener=opener).download("o/r", Artifact(1, "a", 60, False), tmp_path / "a.zip")
    with pytest.raises(CollectError, match="larger than 50"):  # the listing understated the size
        GitHubActions(TOKEN, opener=opener).download("o/r", Artifact(1, "a", 10, False), tmp_path / "b.zip")


def test_artifacts_are_listed() -> None:
    """Name, size and expiry come from the listing."""
    listing = {"artifacts": [{"id": 9, "name": "report-api", "size_in_bytes": 10408, "expired": True}]}
    opener = Opener([("https://api.github.com/repos/o/r/actions/runs/1/artifacts", listing)])

    assert GitHubActions(None, opener=opener).artifacts("o/r", 1) == [Artifact(9, "report-api", 10408, True)]
