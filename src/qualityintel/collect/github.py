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
        """Completed runs, following pages up to ``MAX_PAGES`` x 100 runs."""
        query = urllib.parse.urlencode(
            {
                "branch": branch,
                "status": "completed",
                "created": f">={since.date().isoformat()}",
                "per_page": 100,
            }
        )
        runs: list[WorkflowRun] = []
        for page in range(1, MAX_PAGES + 1):
            data = self._json(
                f"/repos/{repository}/actions/workflows/{urllib.parse.quote(workflow)}/runs?{query}&page={page}"
            )
            batch = data.get("workflow_runs", [])
            runs += [_run(item) for item in batch]
            if len(batch) < 100:
                break
        return runs

    def artifacts(self, repository: str, run_id: int) -> list[Artifact]:
        """Artifacts of a run (up to 100, more than any producer uploads)."""
        data = self._json(f"/repos/{repository}/actions/runs/{run_id}/artifacts?per_page=100")
        return [
            Artifact(
                id=int(a["id"]), name=str(a["name"]), size=int(a["size_in_bytes"]), expired=bool(a["expired"])
            )
            for a in data.get("artifacts", [])
        ]

    def download(self, repository: str, artifact: Artifact, target: Path) -> Path:
        """Download through the redirect GitHub answers with; limited to ``MAX_ARTIFACT_BYTES``."""
        if artifact.size > MAX_ARTIFACT_BYTES:
            raise CollectError(
                f"artifact {artifact.name} has {artifact.size} bytes, more than {MAX_ARTIFACT_BYTES}"
            )
        if not self._token:
            raise CollectError("downloading artifacts needs a token (set GITHUB_TOKEN)", transient=True)
        path = f"/repos/{repository}/actions/artifacts/{artifact.id}/zip"
        try:
            response = self._open(self._request(path))
            location = None
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise _failure(path, error) from None
            location = error.headers.get("Location")
        if location:
            # The storage URL is signed; it gets no Authorization header
            try:
                response = self._open(
                    urllib.request.Request(location, headers={"User-Agent": "qualityintel"})
                )
            except (urllib.error.URLError, OSError) as error:
                raise CollectError(
                    f"artifact {artifact.name}: download failed ({_reason(error)})", transient=True
                ) from None
        target.parent.mkdir(parents=True, exist_ok=True)
        written = 0
        with response, target.open("wb") as sink:
            while chunk := response.read(_CHUNK):
                written += len(chunk)
                if written > MAX_ARTIFACT_BYTES:
                    raise CollectError(f"artifact {artifact.name} is larger than {MAX_ARTIFACT_BYTES} bytes")
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
                data = json.loads(response.read(20 * 1024 * 1024))
        except urllib.error.HTTPError as error:
            raise _failure(path, error) from None
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as error:
            raise CollectError(f"GET {path.split('?')[0]}: {_reason(error)}", transient=True) from None
        if not isinstance(data, dict):
            raise CollectError(f"GET {path.split('?')[0]}: unexpected answer")
        return data


def _run(item: dict[str, Any]) -> WorkflowRun:
    """A workflow run from the API's JSON."""
    started = item.get("run_started_at") or item.get("created_at")
    return WorkflowRun(
        id=int(item["id"]),
        attempt=int(item.get("run_attempt") or 1),
        run_number=int(item.get("run_number") or 0),
        event=str(item.get("event") or ""),
        branch=str(item.get("head_branch") or ""),
        commit=str(item.get("head_sha") or "")[:12],
        conclusion=str(item.get("conclusion") or "unknown"),
        url=str(item.get("html_url") or ""),
        started_at=datetime.fromisoformat(started.replace("Z", "+00:00")) if started else None,
    )


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
