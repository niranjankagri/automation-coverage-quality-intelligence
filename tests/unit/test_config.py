from pathlib import Path

import pytest

from qualityintel.config import (
    DEFAULT_DASHBOARD_HOST,
    DEFAULT_DASHBOARD_PORT,
    DEFAULT_DATABASE,
    ConfigError,
    Settings,
)

pytestmark = pytest.mark.unit


def test_defaults_when_no_variable_is_set() -> None:
    """A clean checkout needs no configuration."""
    settings = Settings.from_env({})

    assert settings == Settings(DEFAULT_DATABASE, DEFAULT_DASHBOARD_HOST, DEFAULT_DASHBOARD_PORT)


def test_values_come_from_the_variables() -> None:
    """Each QI_* variable overrides its default."""
    settings = Settings.from_env(
        {"QI_DATABASE": "data/history.db", "QI_DASHBOARD_HOST": "0.0.0.0", "QI_DASHBOARD_PORT": "9090"}
    )

    assert settings == Settings(Path("data/history.db"), "0.0.0.0", 9090)


def test_empty_variables_fall_back_to_defaults() -> None:
    """`QI_DATABASE=` (set but empty) means "not set", never a file with an empty name."""
    settings = Settings.from_env({"QI_DATABASE": "", "QI_DASHBOARD_HOST": "", "QI_DASHBOARD_PORT": ""})

    assert settings == Settings.from_env({})


def test_reads_os_environ_when_no_mapping_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without an explicit mapping the real process environment is used."""
    monkeypatch.setenv("QI_DASHBOARD_PORT", "8123")

    assert Settings.from_env().dashboard_port == 8123


@pytest.mark.parametrize(
    ("raw", "message"),
    [
        ("eighty", "must be a whole number, got 'eighty'"),
        ("80.5", "must be a whole number"),
        ("0", "between 1 and 65535, got 0"),
        ("65536", "between 1 and 65535, got 65536"),
        ("-1", "between 1 and 65535, got -1"),
    ],
)
def test_invalid_port_is_rejected(raw: str, message: str) -> None:
    """A wrong port stops the tool with a message naming the variable and the value."""
    with pytest.raises(ConfigError, match="QI_DASHBOARD_PORT") as error:
        Settings.from_env({"QI_DASHBOARD_PORT": raw})

    assert message in str(error.value)


@pytest.mark.parametrize("port", ["1", "65535"])
def test_port_limits_are_accepted(port: str) -> None:
    """Both ends of the valid range are allowed."""
    assert Settings.from_env({"QI_DASHBOARD_PORT": port}).dashboard_port == int(port)
