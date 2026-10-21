"""The few GitHub Actions API calls collection needs, with the standard library only.

Listing workflow runs and artifacts of a public repository needs no token, downloading an
artifact does (GitHub answers 401 without one). The token comes from the caller (the command
line reads ``GITHUB_TOKEN``); it is sent only to ``api.github.com`` and never to the storage
host an artifact download redirects to, and it never appears in an error message.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Protocol

API = "https://api.github.com"
MAX_ARTIFACT_BYTES = 150 * 1024 * 1024
MAX_API_RESPONSE_BYTES = 20 * 1024 * 1024
MAX_PAGES = 10
_CHUNK = 1024 * 1024
_TIMEOUT = 60


class CollectError(RuntimeError):
    """A request to the CI system failed (network, permission, rate limit, missing object).

    Attributes:
        transient: The failure says nothing about the run (network, token, rate limit, server
            error): the run must be tried again later, not recorded as incomplete.
    """

    def __init__(self, message: str, transient: bool = False) -> None:
        super().__init__(message)
        self.transient = transient


@dataclass(frozen=True)
class WorkflowRun:
    """One completed workflow run (a pipeline execution) as GitHub reports it."""

    id: int
    attempt: int
    run_number: int
    event: str
    branch: str
    commit: str
    conclusion: str
    url: str
    started_at: datetime | None


@dataclass(frozen=True)
class Artifact:
    """One artifact of a workflow run."""

    id: int
    name: str
    size: int
    expired: bool


class CiSource(Protocol):
    """What collection needs from a CI system; tests use a fake with recorded data."""

    def completed_runs(
        self, repository: str, workflow: str, branch: str, since: datetime
    ) -> list[WorkflowRun]:
        """Completed runs of a workflow on a branch created since ``since``, newest first."""

    def artifacts(self, repository: str, run_id: int) -> list[Artifact]:
        """The artifacts of one run."""

    def download(self, repository: str, artifact: Artifact, target: Path) -> Path:
        """Save an artifact's zip file as ``target`` and return it."""


Opener = Callable[[urllib.request.Request], Any]


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Hand redirects back to the caller, so the token is not sent to another host."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


class GitHubActions:
    """:class:`CiSource` for GitHub Actions over its REST API."""

    def __init__(self, token: str | None, api: str = API, opener: Opener | None = None) -> None:
        self._token = token
        self._api = api.rstrip("/")
        self._open = opener or urllib.request.build_opener(_NoRedirect).open

    def completed_runs(
        self, repository: str, workflow: str, branch: str, since: datetime
    ) -> list[WorkflowRun]:
        """Completed runs, following pages up to ``MAX_PAGES`` x 100 runs.

        Duplicate run attempts can appear when a new run starts while offset-based pagination
        is in progress. Keep the first copy (the API returns newest runs first) and never count
        that same attempt twice in the collection audit.
        """
        query = urllib.parse.urlencode(
            {
                "branch": branch,
                "status": "completed",
                "created": f">={since.date().isoformat()}",
                "per_page": 100,
            }
        )
        runs: list[WorkflowRun] = []
        seen: set[tuple[int, int]] = set()
        reported_total: int | None = None
        for page in range(1, MAX_PAGES + 1):
            path = (
                f"/repos/{repository}/actions/workflows/{urllib.parse.quote(workflow)}"
                f"/runs?{query}&page={page}"
            )
            data = self._json(path)
            batch = _objects(data, "workflow_runs", path)
            page_total = _optional_count(data.get("total_count"), path)
            if page == 1:
                reported_total = page_total
            elif reported_total is not None and page_total is not None and page_total != reported_total:
                raise CollectError(
                    f"GET {path.split('?')[0]}: run listing changed during pagination; retry collection",
                    transient=True,
                )
            for item in batch:
                try:
                    run = _run(item)
                except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
                    raise _malformed(path, "workflow run") from None
                key = (run.id, run.attempt)
                if key not in seen:
                    seen.add(key)
                    runs.append(run)
            if len(batch) < 100:
                break
            if page == MAX_PAGES and (reported_total is None or reported_total > len(runs)):
                raise CollectError(
                    f"GET {path.split('?')[0]}: more than {MAX_PAGES * 100} runs; "
                    "reduce --days or increase MAX_PAGES"
                )
        if reported_total is not None and reported_total > len(runs):
            raise CollectError(
                f"GET {path.split('?')[0]}: GitHub listed {reported_total} runs but only "
                f"{len(runs)} were read",
                transient=True,
            )
        return runs

    def artifacts(self, repository: str, run_id: int) -> list[Artifact]:
        """Artifacts of a run, following all pages within the configured safety bound."""
        artifacts: list[Artifact] = []
        seen: set[int] = set()
        reported_total: int | None = None
        for page in range(1, MAX_PAGES + 1):
            path = f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100&page={page}"
            data = self._json(path)
            batch = _objects(data, "artifacts", path)
            page_total = _optional_count(data.get("total_count"), path)
            if page == 1:
                reported_total = page_total
            elif reported_total is not None and page_total is not None and page_total != reported_total:
                raise CollectError(
                    f"GET {path.split('?')[0]}: artifact listing changed during pagination; retry collection",
                    transient=True,
                )
            for item in batch:
                try:
                    artifact = _artifact(item)
                except (AttributeError, KeyError, OverflowError, TypeError, ValueError):
                    raise _malformed(path, "artifact") from None
                if artifact.id not in seen:
                    seen.add(artifact.id)
                    artifacts.append(artifact)
            if len(batch) < 100:
                break
            if page == MAX_PAGES and (reported_total is None or reported_total > len(artifacts)):
                raise CollectError(
                    f"GET {path.split('?')[0]}: more than {MAX_PAGES * 100} artifacts; response is incomplete"
                )
        if reported_total is not None and reported_total > len(artifacts):
            raise CollectError(
                f"GET {path.split('?')[0]}: GitHub listed {reported_total} artifacts but only "
                f"{len(artifacts)} were read",
                transient=True,
            )
        return artifacts

    def download(self, repository: str, artifact: Artifact, target: Path) -> Path:
        """Download through the redirect GitHub answers with; limited to ``MAX_ARTIFACT_BYTES``."""
        if artifact.size > MAX_ARTIFACT_BYTES:
            raise CollectError(
                f"artifact {artifact.name!r} has {artifact.size} bytes, more than {MAX_ARTIFACT_BYTES}"
            )
        if not self._token:
            raise CollectError("downloading artifacts needs a token (set GITHUB_TOKEN)", transient=True)
        path = f"/repos/{repository}/actions/artifacts/{artifact.id}/zip"
        response = None
        location = None
        try:
            response = self._open(self._request(path))
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise _failure(path, error) from None
            location = error.headers.get("Location")
        if location:
            if not location.startswith("https://"):
                raise CollectError(f"artifact {artifact.name!r}: storage redirect is not HTTPS")
            # The storage URL is signed; it gets no Authorization header
            try:
                response = self._open(
                    urllib.request.Request(location, headers={"User-Agent": "qualityintel"})
                )
            except (urllib.error.URLError, OSError) as error:
                raise CollectError(
                    f"artifact {artifact.name!r}: download failed ({_reason(error)})", transient=True
                ) from None
        elif response is None:
            raise CollectError(
                f"artifact {artifact.name!r}: GitHub redirect had no Location header", transient=True
            )
        assert response is not None
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with response, target.open("wb") as sink:
            while chunk := response.read(_CHUNK):
                written += len(chunk)
                if written > MAX_ARTIFACT_BYTES:
                    raise CollectError(
                        f"artifact {artifact.name!r} is larger than {MAX_ARTIFACT_BYTES} bytes"
                    )
                sink.write(chunk)
        return target

    # ---- internals -----------------------------------------------------------------------

    def _request(self, path: str) -> urllib.request.Request:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "qualityintel",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return urllib.request.Request(self._api + path, headers=headers)

    def _json(self, path: str) -> dict[str, Any]:
        try:
            with self._open(self._request(path)) as response:
                body = response.read(MAX_API_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            raise _failure(path, error) from None
        except (urllib.error.URLError, OSError) as error:
            raise CollectError(f"GET {path.split('?')[0]}: {_reason(error)}", transient=True) from None
        if len(body) > MAX_API_RESPONSE_BYTES:
            raise CollectError(
                f"GET {path.split('?')[0]}: response exceeds {MAX_API_RESPONSE_BYTES} bytes", transient=True
            )
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, RecursionError, UnicodeDecodeError):
            raise CollectError(f"GET {path.split('?')[0]}: malformed JSON response", transient=True) from None
        if not isinstance(data, dict):
            raise CollectError(f"GET {path.split('?')[0]}: unexpected JSON answer", transient=True)
        return data


def _run(item: dict[str, Any]) -> WorkflowRun:
    """A workflow run from the API's JSON."""
    started = item.get("run_started_at") or item.get("created_at")
    if started is not None and not isinstance(started, str):
        raise ValueError("invalid timestamp")
    return WorkflowRun(
        id=_positive_int(item["id"], "id"),
        attempt=_positive_int(item.get("run_attempt") or 1, "run_attempt"),
        run_number=_nonnegative_int(item.get("run_number") or 0, "run_number"),
        event=_optional_string(item.get("event"), "event"),
        branch=_optional_string(item.get("head_branch"), "head_branch"),
        commit=_optional_string(item.get("head_sha"), "head_sha")[:12],
        conclusion=_optional_string(item.get("conclusion"), "conclusion") or "unknown",
        url=_optional_string(item.get("html_url"), "html_url"),
        started_at=datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None,
    )


def _artifact(item: dict[str, Any]) -> Artifact:
    """One artifact row from GitHub's API, with fields checked instead of coerced."""
    name = item["name"]
    expired = item["expired"]
    if (
        not isinstance(name, str)
        or not name
        or len(name) > 200
        or any(ord(char) < 32 or ord(char) == 127 for char in name)
        or type(expired) is not bool
    ):
        raise ValueError("invalid artifact fields")
    return Artifact(
        id=_positive_int(item["id"], "id"),
        name=name,
        size=_nonnegative_int(item["size_in_bytes"], "size_in_bytes"),
        expired=expired,
    )


def _objects(data: dict[str, Any], field: str, path: str) -> list[dict[str, Any]]:
    """A required array of JSON objects returned by GitHub."""
    rows = data.get(field)
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise _malformed(path, field)
    return rows


def _optional_count(value: Any, path: str) -> int | None:
    """GitHub's optional total_count, if present."""
    if value is None:
        return None
    try:
        return _nonnegative_int(value, "total_count")
    except ValueError:
        raise _malformed(path, "total_count") from None


def _positive_int(value: Any, name: str) -> int:
    """An API integer greater than zero."""
    if type(value) is not int or value < 1:
        raise ValueError(f"invalid {name}")
    return value


def _nonnegative_int(value: Any, name: str) -> int:
    """An API integer that may be zero."""
    if type(value) is not int or value < 0:
        raise ValueError(f"invalid {name}")
    return value


def _optional_string(value: Any, name: str) -> str:
    """A string or a documented nullable field."""
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"invalid {name}")
    return value


def _malformed(path: str, field: str) -> CollectError:
    """A malformed API response should be visible and retried, never misread as empty data."""
    return CollectError(f"GET {path.split('?')[0]}: malformed {field} response", transient=True)


def _failure(path: str, error: urllib.error.HTTPError) -> CollectError:
    """A readable error for an HTTP failure (no headers, so no token, in the message)."""
    hint = {401: "token missing or invalid", 403: "forbidden or rate limited", 404: "not found or expired"}
    transient = error.code in (401, 403, 429) or error.code >= 500
    return CollectError(
        f"GET {path.split('?')[0]}: HTTP {error.code} ({hint.get(error.code, error.reason)})",
        transient=transient,
    )


def _reason(error: BaseException) -> str:
    """The cause of a network error, without request details."""
    return str(getattr(error, "reason", None) or error)
