"""Small, strict URL checks for links copied from CI metadata."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

_GITHUB_RUN_PATH = re.compile(r"^/[^/]+/[^/]+/actions/runs/[0-9]+(?:/attempts/[1-9][0-9]*)?/?$")
_CONTROL = re.compile(r"[\x00-\x20\x7f]")


def github_run_url(value: str | None) -> str | None:
    """Return a GitHub Actions run URL, otherwise ``None``.

    CI metadata is external input. Checking only for an ``https://github.com`` prefix also
    accepts lookalike hosts and user-info URLs such as ``github.com@evil.example``.
    """
    if not value or len(value) > 2_000 or _CONTROL.search(value) or "\\" in value:
        return None
    try:
        parts = urlsplit(value)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if (
        parts.scheme.lower() != "https"
        or host is None
        or host.lower() != "github.com"
        or port is not None
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or not _GITHUB_RUN_PATH.fullmatch(parts.path)
    ):
        return None
    return value


def dashboard_path(value: str | None) -> str | None:
    """Accept a same-site root-relative dashboard link, never an external destination."""
    if not value or len(value) > 2_000 or _CONTROL.search(value) or "\\" in value:
        return None
    try:
        parts = urlsplit(value)
    except ValueError:
        return None
    if parts.scheme or parts.netloc or not parts.path.startswith("/") or parts.path.startswith("//"):
        return None
    return value
