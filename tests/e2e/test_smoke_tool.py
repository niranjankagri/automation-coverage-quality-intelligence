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


def test_collected_requires_collection_records(base_url: str, collected_url: str) -> None:
    """The samples have no collection records: --collected fails there, passes with records."""
    assert smoke.main([base_url, "--collected"]) == 1
    assert smoke.main([collected_url, "--collected"]) == 0


def test_an_unreachable_service_fails() -> None:
    """Nothing listening: exit 1 with a reason, not a traceback."""
    assert smoke.main(["http://127.0.0.1:9"]) == 1
