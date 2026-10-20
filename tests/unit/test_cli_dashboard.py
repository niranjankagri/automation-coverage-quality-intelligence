from pathlib import Path
from typing import Any

import pytest
import uvicorn

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
