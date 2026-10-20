import pytest

from qualityintel import __version__
from qualityintel.cli import EXIT_OK, EXIT_USAGE, main

pytestmark = pytest.mark.unit


def test_version_prints_the_package_version(capsys: pytest.CaptureFixture[str]) -> None:
    """`qi version` prints the version and succeeds."""
    assert main(["version"]) == EXIT_OK

    assert capsys.readouterr().out == f"qi {__version__}\n"


def test_config_prints_the_settings_in_effect(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """`qi config` shows the values read from the environment."""
    monkeypatch.setenv("QI_DATABASE", "data/history.db")
    monkeypatch.setenv("QI_DASHBOARD_PORT", "9090")
    monkeypatch.delenv("QI_DASHBOARD_HOST", raising=False)

    assert main(["config"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "data" in out
    assert "history.db" in out
    assert "dashboard host  127.0.0.1" in out
    assert "dashboard port  9090" in out


def test_config_error_gives_a_message_and_usage_exit_code(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """An invalid variable is reported on stderr without a traceback, exit code 2."""
    monkeypatch.setenv("QI_DASHBOARD_PORT", "eighty")

    assert main(["config"]) == EXIT_USAGE

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("qi: configuration error: QI_DASHBOARD_PORT")


def test_no_command_prints_help_and_signals_wrong_usage(capsys: pytest.CaptureFixture[str]) -> None:
    """Running `qi` alone lists the commands and returns exit code 2."""
    assert main([]) == EXIT_USAGE

    err = capsys.readouterr().err
    assert "usage: qi" in err
    assert "version" in err
    assert "config" in err


def test_unknown_command_exits_with_usage_code(capsys: pytest.CaptureFixture[str]) -> None:
    """An unknown command is rejected by argparse with exit code 2 (the same code as no command)."""
    with pytest.raises(SystemExit) as stop:
        main(["publish"])

    assert stop.value.code == EXIT_USAGE
    assert "invalid choice: 'publish'" in capsys.readouterr().err
