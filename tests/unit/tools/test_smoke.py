"""Regression tests for fail-closed live smoke monitoring."""

import json
from unittest.mock import patch

import pytest

from tools import smoke

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"[]",
        b"null",
        json.dumps({"status": "ok", "runs": {"unexpected": "shape"}}).encode(),
    ],
)
def test_smoke_reports_malformed_health_without_traceback(
    body: bytes, capsys: pytest.CaptureFixture[str]
) -> None:
    """Bad JSON and incompatible response shapes must fail the check cleanly."""
    with patch.object(smoke, "get", return_value=(200, {}, body)):
        assert smoke.main(["http://127.0.0.1:8000"]) == 1
    assert "FAIL" in capsys.readouterr().out


def test_smoke_reports_invalid_collection_timestamp_without_traceback(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A bad timestamp from /api/status must not crash the scheduled monitor."""
    def fake_get(url: str) -> tuple[int, dict[str, str], bytes]:
        if url.endswith("/api/health"):
            return 200, {}, b'{"status":"ok","runs":1}'
        if url.endswith("/api/status"):
            return 200, {}, b'{"stale":false,"latest_collection_at":"not-a-date"}'
        if url.endswith("/api/readiness"):
            return 200, {"cache-control": "no-cache"}, b'{"state":"ready"}'
        return (
            200,
            {"content-security-policy": "script-src 'self'", "x-content-type-options": "nosniff"},
            b"ok",
        )

    with patch.object(smoke, "get", side_effect=fake_get):
        assert smoke.main(["http://127.0.0.1:8000", "--max-collection-age", "30"]) == 1
    assert "FAIL" in capsys.readouterr().out
