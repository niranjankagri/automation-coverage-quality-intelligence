"""Smoke test of a running dashboard: python tools/smoke.py URL [--wait S] [--collected] [--max-age H].

Checks what a visitor and an operator rely on (docs/deployment.md): the page and its security
headers, health, freshness, and that the API answers with data. Over https it also expects HSTS.
``--collected`` additionally requires collected pipelines (the hosted demonstration). Exit code
0 when every check passed, 1 otherwise; one line per check.

``--wait`` retries the first request for that long: a free host that was asleep needs about a
minute to start. ``--max-collection-age HOURS`` fails when the latest collection is older (the
collection stopped, or the dashboard did not pick it up). A failed check prints what to look at:
the daily live workflow fails, and GitHub notifies the repository owner (docs/operations.md).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from typing import Any

# What to look at when a check fails (docs/operations.md, Incidents)
HINTS = {
    "data not stale": "the dashboard cannot reload its data: see last_error in /api/status, then the log",
    "collection recent": "no collection published lately: open the Collect CI results workflow (failed?)",
    "no repeated incomplete collections": "pipelines are being recorded incomplete: open the Collection page",
}

TIMEOUT = 30
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _read_bounded(response: Any) -> bytes:
    """Reject oversized responses rather than buffering an unbounded remote payload."""
    body: bytes = response.read(MAX_RESPONSE_BYTES + 1)
    if len(body) > MAX_RESPONSE_BYTES:
        raise ValueError("smoke response exceeds 2 MiB limit")
    return body


def get(url: str) -> tuple[int, dict[str, str], bytes]:
    """Status, headers (names in lower case) and body of a GET request (HTTP errors are answers too)."""
    request = urllib.request.Request(url, headers={"User-Agent": "qualityintel-smoke"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return response.status, _lower(response.headers.items()), _read_bounded(response)
    except urllib.error.HTTPError as error:
        return error.code, _lower(error.headers.items()), _read_bounded(error)


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


def checks(base: str, collected: bool, max_age_hours: float | None = None) -> list[tuple[str, bool, str]]:
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

    status, _, body = get(f"{base}/api/executions")
    execution = json.loads(body) if status == 200 else {}
    counts = execution.get("counts", {})
    results.append(
        (
            "execution dashboard reconciles",
            status == 200
            and execution.get("executions", 0) > 0
            and sum(counts.values()) == execution.get("executions"),
            f"{execution.get('executions')} executions",
        )
    )
    status, _, body = get(f"{base}/api/execution-options")
    options = json.loads(body) if status == 200 else []
    results.append(
        ("guided navigation available", status == 200 and bool(options), f"{len(options)} recorded contexts")
    )
    for path in ("/", "/static/app.js", "/static/style.css"):
        status, headers, _ = get(f"{base}{path}")
        results.append(
            (
                f"{path} revalidates",
                status == 200 and "no-" in headers.get("cache-control", ""),
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
    if max_age_hours is not None:
        latest = state.get("latest_collection_at")
        age = (
            (datetime.now(UTC) - datetime.fromisoformat(latest.replace("Z", "+00:00"))).total_seconds() / 3600
            if latest
            else None
        )
        results.append(
            (
                "collection recent",
                age is not None and age <= max_age_hours,
                f"latest {latest or 'never'}, {age:.1f} h ago, limit {max_age_hours:g} h"
                if age is not None
                else "no collection recorded",
            )
        )
        incomplete = int(state.get("incomplete_collections_7d") or 0)
        results.append(
            (
                "no repeated incomplete collections",
                incomplete < 3,
                f"{incomplete} incomplete in 7 days (3 or more fail)",
            )
        )
    return results


def main(argv: list[str] | None = None) -> int:
    """Run the checks and print one line per check."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("url", help="base address, e.g. https://quality-intelligence.onrender.com")
    parser.add_argument("--wait", type=float, default=0, help="seconds to wait for the service to wake up")
    parser.add_argument("--collected", action="store_true", help="also require collected pipelines")
    parser.add_argument(
        "--max-collection-age", type=float, metavar="HOURS", help="fail when the latest collection is older"
    )
    args = parser.parse_args(argv)
    base = args.url.rstrip("/")
    wait_until_up(base, args.wait)
    try:
        results = checks(base, args.collected, args.max_collection_age)
    except (
        urllib.error.URLError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        OverflowError,
    ) as error:
        # A malformed or schema-incompatible live API response is a failed health check,
        # not an uncaught traceback that hides the incident from the operator.
        print(f"FAIL  {base} cannot be checked: {error}")
        return 1
    for name, passed, detail in results:
        print(f"{'ok  ' if passed else 'FAIL'}  {name}{f'  ({detail})' if detail else ''}")
        if not passed and name in HINTS:
            print(f"      what to do: {HINTS[name]}")
    return 0 if all(passed for _, passed, _ in results) else 1


if __name__ == "__main__":
    sys.exit(main())
