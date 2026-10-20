"""Runtime settings read from environment variables.

Every setting has a default, so a clean checkout works without any configuration.
``.env.example`` lists the same variables; ``qi config`` prints the values in effect.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_DATABASE = Path(".qi") / "quality.db"
DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8000
DEFAULT_DASHBOARD_USER = "qi"
DEFAULT_REFRESH_SECONDS = 30.0
DEFAULT_COLLECTION_HOURS = 26.0
MIN_PASSWORD_LENGTH = 12


class ConfigError(ValueError):
    """An environment variable holds a value the tool cannot use."""


@dataclass(frozen=True)
class Settings:
    """Settings in effect for one run.

    Attributes:
        database: SQLite file for the execution history.
        dashboard_host: Address the dashboard listens on.
        dashboard_port: TCP port the dashboard listens on.
        dashboard_user: User name for the dashboard's basic authentication.
        dashboard_password: Password that turns basic authentication on (``None``: off, and
            then the dashboard only serves on this machine). Never printed: left out of repr.
    """

    database: Path
    dashboard_host: str
    dashboard_port: int
    dashboard_user: str = DEFAULT_DASHBOARD_USER
    dashboard_password: str | None = field(default=None, repr=False)
    refresh_seconds: float = DEFAULT_REFRESH_SECONDS
    collection_hours: float = DEFAULT_COLLECTION_HOURS
    collection_url: str | None = None

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Settings:
        """Build the settings from environment variables.

        A missing or empty variable falls back to its default, so ``QI_DATABASE=`` behaves
        like not setting it at all instead of meaning "a file with an empty name".

        Args:
            env: Variables to read; ``os.environ`` when omitted (tests pass a plain dict).

        Returns:
            The settings in effect.

        Raises:
            ConfigError: A variable is set to a value that cannot be used.
        """
        source = os.environ if env is None else env
        return cls(
            database=Path(source.get("QI_DATABASE") or DEFAULT_DATABASE),
            dashboard_host=source.get("QI_DASHBOARD_HOST") or DEFAULT_DASHBOARD_HOST,
            dashboard_port=_parse_port(source.get("QI_DASHBOARD_PORT")),
            dashboard_user=source.get("QI_DASHBOARD_USER") or DEFAULT_DASHBOARD_USER,
            dashboard_password=_check_password(source.get("QI_DASHBOARD_PASSWORD")),
            refresh_seconds=_parse_seconds(source.get("QI_REFRESH_SECONDS")),
            collection_hours=_parse_hours(source.get("QI_COLLECTION_HOURS")),
            collection_url=_check_url(source.get("QI_COLLECTION_URL")),
        )


def _check_password(raw: str | None) -> str | None:
    """``QI_DASHBOARD_PASSWORD``: empty means no password; a short one is refused, not weakened."""
    if not raw:
        return None
    if len(raw) < MIN_PASSWORD_LENGTH:
        # The value itself is never part of the message
        raise ConfigError(f"QI_DASHBOARD_PASSWORD must have at least {MIN_PASSWORD_LENGTH} characters")
    return raw


def _parse_seconds(raw: str | None) -> float:
    """``QI_REFRESH_SECONDS``: how often the dashboard looks for new data; 0 turns it off."""
    if not raw:
        return DEFAULT_REFRESH_SECONDS
    try:
        seconds = float(raw)
    except ValueError:
        raise ConfigError(f"QI_REFRESH_SECONDS must be a number of seconds, got {raw!r}") from None
    if not 0 <= seconds <= 86_400:
        raise ConfigError(f"QI_REFRESH_SECONDS must be between 0 and 86400, got {raw}")
    return seconds


def _parse_hours(raw: str | None) -> float:
    """``QI_COLLECTION_HOURS``: after how many hours a repository's last collection is overdue."""
    if not raw:
        return DEFAULT_COLLECTION_HOURS
    try:
        hours = float(raw)
    except ValueError:
        raise ConfigError(f"QI_COLLECTION_HOURS must be a number of hours, got {raw!r}") from None
    if not 1 <= hours <= 24 * 90:
        raise ConfigError(f"QI_COLLECTION_HOURS must be between 1 and 2160, got {raw}")
    return hours


def _check_url(raw: str | None) -> str | None:
    """``QI_COLLECTION_URL``: an https link (it becomes a link on the page)."""
    if not raw:
        return None
    if not raw.startswith("https://"):
        raise ConfigError("QI_COLLECTION_URL must be an https:// address")
    return raw


def _parse_port(raw: str | None) -> int:
    """Parse ``QI_DASHBOARD_PORT``; fail loudly instead of starting on a surprising port."""
    if not raw:
        return DEFAULT_DASHBOARD_PORT
    try:
        port = int(raw)
    except ValueError:
        raise ConfigError(f"QI_DASHBOARD_PORT must be a whole number, got {raw!r}") from None
    if not 1 <= port <= 65535:
        raise ConfigError(f"QI_DASHBOARD_PORT must be between 1 and 65535, got {port}")
    return port
