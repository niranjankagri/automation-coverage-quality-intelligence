"""Smoke test of a running dashboard: python tools/smoke.py URL [--wait SECONDS] [--collected].

Checks what a visitor and an operator rely on (docs/deployment.md): the page and its security
headers, health, freshness, and that the API answers with data. Over https it also expects HSTS.
``--collected`` additionally requires collected pipelines (the hosted demonstration). Exit code
0 when every check passed, 1 otherwise; one line per check.

``--wait`` retries the first request for that long: a free host that was asleep needs about a
minute to start.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from typing import Any

TIMEOUT = 30


def get(url: str) -> tuple[int, dict[str, str], bytes]:
    """Status, headers (names in lower case) and body of a GET request (HTTP errors are answers too)."""
    request = urllib.request.Request(url, headers={"User-Agent": "qualityintel-smoke"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, _lower(response.headers.items()), response.read()
    except urllib.error.HTTPError as error:
        return error.code, _lower(error.headers.items()), error.read()


def _lower(items: Any) -> dict[str, str]:
    """Header names are case-insensitive; servers send them in either case."""
    return {name.lower(): value for name, value in items}


def wait_until_up(base: str, seconds: float) -> None:
    """Retry /api/health until it answers or the time is up."""
    deadline = time.monotonic() + seconds
    while True:
        try:
            if get(f"{base}/api/health")[0] == 200:
                return
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        if time.monotonic() >= deadline:
            return
        time.sleep(5)


def checks(base: str, collected: bool) -> list[tuple[str, bool, str]]:
    """Every check as (name, passed, detail)."""
    results: list[tuple[str, bool, str]] = []

    status, headers, body = get(f"{base}/")
    results.append(("page answers 200", status == 200, str(status)))
    policy = headers.get("content-security-policy", "")
    results.append(("strict content security policy", "script-src 'self'" in policy, policy[:60]))
    results.append(("nosniff", headers.get("x-content-type-options") == "nosniff", ""))
    if base.startswith("https://"):
        hsts = headers.get("strict-transport-security", "")
        results.append(("HSTS over https", hsts.startswith("max-age="), hsts))

    status, _, body = get(f"{base}/api/health")
    health: dict[str, Any] = json.loads(body) if status == 200 else {}
    results.append(("health ok", health.get("status") == "ok", f"{health.get('runs')} runs"))
    results.append(("runs loaded", int(health.get("runs") or 0) > 0, str(health.get("runs"))))

    status, _, body = get(f"{base}/api/status")
    state: dict[str, Any] = json.loads(body) if status == 200 else {}
    results.append(
        ("data not stale", status == 200 and state.get("stale") is False, str(state.get("last_error")))
    )

    status, headers, body = get(f"{base}/api/readiness")
    readiness = json.loads(body) if status == 200 else {}
    results.append(
        (
            "readiness decided",
            readiness.get("state") in {"ready", "at risk", "blocked", "unknown"},
            str(readiness.get("state")),
        )
    )
    results.append(
        (
            "API not cached as stale",
            "no-" in headers.get("cache-control", ""),
            headers.get("cache-control", ""),
        )
    )

    if collected:
        results.append(
            ("collections recorded", int(state.get("collections") or 0) > 0, str(state.get("collections")))
        )
        status, _, body = get(f"{base}/api/pipelines")
        pipelines = json.loads(body) if status == 200 else {}
        rows = pipelines.get("pipelines", []) if isinstance(pipelines, dict) else pipelines
        results.append(("pipelines listed", status == 200 and len(rows) > 0, f"{len(rows)} pipelines"))
    return results


def main(argv: list[str] | None = None) -> int:
    """Run the checks and print one line per check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="base address, e.g. https://quality-intelligence.onrender.com")
    parser.add_argument("--wait", type=float, default=0, help="seconds to wait for the service to wake up")
    parser.add_argument("--collected", action="store_true", help="also require collected pipelines")
    args = parser.parse_args(argv)
    base = args.url.rstrip("/")
    wait_until_up(base, args.wait)
    try:
        results = checks(base, args.collected)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as error:
        print(f"FAIL  {base} cannot be checked: {error}")
        return 1
    for name, passed, detail in results:
        print(f"{'ok  ' if passed else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
