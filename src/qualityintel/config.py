"""Runtime settings read from environment variables.

Every setting has a default, so a clean checkout works without any configuration.
``.env.example`` lists the same variables; ``qi config`` prints the values in effect.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DATABASE = Path(".qi") / "quality.db"
DEFAULT_DASHBOARD_HOST = "127.0.0.1"
DEFAULT_DASHBOARD_PORT = 8000


class ConfigError(ValueError):
    """An environment variable holds a value the tool cannot use."""


@dataclass(frozen=True)
class Settings:
    """Settings in effect for one run.

    Attributes:
        database: SQLite file for the execution history.
        dashboard_host: Address the dashboard listens on.
        dashboard_port: TCP port the dashboard listens on.
    """

    database: Path
    dashboard_host: str
    dashboard_port: int

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
        )


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
