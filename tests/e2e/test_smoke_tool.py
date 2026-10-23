"""tools/smoke.py against a real server: passes on a healthy dashboard, fails where it should."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[2] / "tools"))
import smoke

pytestmark = pytest.mark.e2e


def test_every_check_passes_on_the_sample_dashboard(
    base_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Page, headers, health, freshness, readiness, cache rule: all ok (no https, so no HSTS)."""
    assert smoke.main([base_url]) == 0
    out = capsys.readouterr().out
    assert "FAIL" not in out
    assert "HSTS" not in out
    assert "report asset /next/" in out
    assert "report asset /static/next/js/overview.js" in out
    assert "report overview reconciles" in out


def test_collected_requires_collection_records(base_url: str, collected_url: str) -> None:
    """The samples have no collection records: --collected fails there, passes with records."""
    assert smoke.main([base_url, "--collected"]) == 1
    assert smoke.main([collected_url, "--collected"]) == 0


def test_an_unreachable_service_fails() -> None:
    """Nothing listening: exit 1 with a reason, not a traceback."""
    assert smoke.main(["http://127.0.0.1:9"]) == 1


def test_an_old_collection_fails_with_what_to_do(
    collected_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--max-collection-age: a generous limit passes, a tight one fails and says where to look."""
    assert smoke.main([collected_url, "--collected", "--max-collection-age", "100000"]) == 0
    capsys.readouterr()

    assert smoke.main([collected_url, "--collected", "--max-collection-age", "1"]) == 1
    out = capsys.readouterr().out
    assert "FAIL  collection recent" in out
    assert "what to do: no collection published lately" in out


def test_report_drilldowns_pass_on_collected_data(
    collected_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Repository selection, a test's own execution and a requirement answer as the report needs."""
    assert smoke.main([collected_url, "--collected"]) == 0
    out = capsys.readouterr().out
    for check in (
        "report filter choices",
        "repository selection narrows the report",
        "test drill-down opens its own execution",
        "coverage drill-down opens a requirement",
    ):
        assert f"ok    {check}" in out


def test_a_deployment_that_does_not_run_the_expected_commit_fails(
    base_url: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """--expect-commit: the service still runs another commit after the wait, so the smoke fails."""
    assert smoke.main([base_url, "--expect-commit", "0000000deadbeef", "--wait", "0"]) == 1
    assert "FAIL  deployed commit" in capsys.readouterr().out


@pytest.mark.usefixtures("chromium_only")
def test_the_browser_report_smoke_passes_on_collected_data(collected_url: str) -> None:
    """tools/report_smoke.py in its own process; it starts its own Chromium, so only in that job."""
    import subprocess

    done = subprocess.run(
        [sys.executable, str(Path(__file__).parents[2] / "tools" / "report_smoke.py"), collected_url],
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )

    assert done.returncode == 0, done.stdout + done.stderr
    assert "ok    test drill-down opens its own execution" in done.stdout
    assert "ok    no application errors" in done.stdout
