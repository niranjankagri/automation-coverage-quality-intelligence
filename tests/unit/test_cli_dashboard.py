from pathlib import Path
from typing import Any

import pytest
import uvicorn
from fastapi.testclient import TestClient

from qualityintel.cli import EXIT_INPUT, EXIT_OK, EXIT_USAGE, main

pytestmark = pytest.mark.unit

SAMPLES = Path(__file__).parents[2] / "samples"


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Replace uvicorn.run so the command returns instead of serving forever."""
    calls: dict[str, Any] = {}

    def fake_run(app: object, **options: Any) -> None:
        calls["app"] = app
        calls.update(options)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    return calls


def test_dashboard_serves_the_loaded_workspace(
    served: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    """Defaults come from the settings; the start line names the data size."""
    code = main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml"), str(SAMPLES / "results")])

    assert code == EXIT_OK
    assert (served["host"], served["port"]) == ("127.0.0.1", 8000)
    assert "(42 requirements, 43 runs)" in capsys.readouterr().out


def test_host_and_port_options_win(served: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """Command line beats QI_DASHBOARD_* variables."""
    monkeypatch.setenv("QI_DASHBOARD_PORT", "9000")
    monkeypatch.setenv("QI_DASHBOARD_PASSWORD", "correct horse battery")  # needed off this machine

    main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml"), "--host", "0.0.0.0", "--port", "8123"])

    assert (served["host"], served["port"]) == ("0.0.0.0", 8123)


def test_environment_port_is_used_without_option(
    served: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """QI_DASHBOARD_PORT applies when --port is not given."""
    monkeypatch.setenv("QI_DASHBOARD_PORT", "9000")

    main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml")])

    assert served["port"] == 9000


def test_dashboard_refuses_incomplete_input(served: dict[str, Any], tmp_path: Path) -> None:
    """Broken results: no server is started, exit code 3."""
    (tmp_path / "broken.xml").write_text("<testsuite", encoding="utf-8")

    assert main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml"), str(tmp_path)]) == EXIT_INPUT
    assert served == {}


def test_dashboard_reports_bad_configuration(served: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> None:
    """A wrong QI_DASHBOARD_PORT is a usage error, not a crash."""
    monkeypatch.setenv("QI_DASHBOARD_PORT", "eighty")

    assert main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml")]) == EXIT_USAGE
    assert served == {}


def test_dashboard_loads_runs_from_the_history_database(
    served: dict[str, Any], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """--database adds stored runs; files given as well are not counted twice."""
    database = tmp_path / "h.db"
    assert main(["history", "import", str(SAMPLES / "results"), "--database", str(database)]) == EXIT_OK
    capsys.readouterr()

    code = main(
        [
            "dashboard",
            "--catalog",
            str(SAMPLES / "catalog.toml"),
            str(SAMPLES / "results"),
            "--database",
            str(database),
        ]
    )

    assert code == EXIT_OK
    assert "(42 requirements, 43 runs)" in capsys.readouterr().out


@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.20", "::", "dashboard.example.com"])
def test_no_unauthenticated_dashboard_off_this_machine(
    served: dict[str, Any], capsys: pytest.CaptureFixture[str], host: str
) -> None:
    """Without QI_DASHBOARD_PASSWORD only loopback addresses are served (exit 2 otherwise)."""
    code = main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml"), "--host", host])

    assert code == EXIT_USAGE
    assert served == {}
    assert "refusing to serve the dashboard" in capsys.readouterr().err


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2", "localhost", "::1", "[::1]"])
def test_loopback_needs_no_password(served: dict[str, Any], host: str) -> None:
    """This machine only: served as before."""
    assert main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml"), "--host", host]) == EXIT_OK


def test_with_a_password_the_app_requires_the_login(
    served: dict[str, Any], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The password reaches the app, the start line says a login is required, TLS is advised."""
    monkeypatch.setenv("QI_DASHBOARD_USER", "lead")
    monkeypatch.setenv("QI_DASHBOARD_PASSWORD", "correct horse battery")

    assert main(["dashboard", "--catalog", str(SAMPLES / "catalog.toml"), "--host", "0.0.0.0"]) == EXIT_OK

    client = TestClient(served["app"])
    assert client.get("/api/health").status_code == 401
    assert client.get("/api/health", auth=("lead", "correct horse battery")).status_code == 200
    out, err = capsys.readouterr()
    assert "login required (user lead)" in out
    assert "behind TLS" in err
    assert "correct horse battery" not in out + err


def test_config_never_prints_the_password(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Qi config says whether a password is set, not what it is."""
    monkeypatch.setenv("QI_DASHBOARD_PASSWORD", "correct horse battery")

    assert main(["config"]) == EXIT_OK

    out = capsys.readouterr().out
    assert "password set" in out
    assert "correct horse battery" not in out
