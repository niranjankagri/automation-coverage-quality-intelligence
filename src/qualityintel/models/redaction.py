"""Remove secrets from failure messages before they are stored or reported (docs/security.md).

Failure messages are the one piece of test output this platform keeps (logs are never read),
and assertion messages do contain secrets: a request dump with its ``Authorization`` header, a
connection string, a token in a URL. Every :class:`~qualityintel.models.results.FailureDetails`
passes through :func:`redact`, so no importer, report or dashboard view can show one.

The patterns target the shapes secrets have, not words: "expected token count 3" stays as it is,
``token=abc123`` does not. This is a safety net, not a guarantee; secrets in unusual shapes
pass through, so test suites should still not print them.
"""

from __future__ import annotations

import re

REDACTED = "[redacted]"

# Key names whose value is a secret when written as ``name=value`` or ``name: value``
_SECRET_KEYS = (
    r"password|passwd|pwd|secret|client[_-]?secret|api[_-]?key|apikey|access[_-]?key|"
    r"secret[_-]?key|private[_-]?key|access[_-]?token|refresh[_-]?token|auth[_-]?token|"
    r"session[_-]?id|token"
)

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # PEM private keys, whole block
    (
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL),
        f"{REDACTED} private key",
    ),
    # Authorization: Bearer <token> / Basic <base64> (headers in request dumps, JSON or text)
    (
        re.compile(r"(?i)(\bauthorization[\"']?\s*[:=]\s*[\"']?)(?:(?:bearer|basic|token)\s+)?[^\s\"',;}]+"),
        rf"\1{REDACTED}",
    ),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{8,}"), f"Bearer {REDACTED}"),
    # password=..., "api_key": "...", token: ...
    (
        re.compile(
            rf"(?i)(\b(?:{_SECRET_KEYS})[\"']?\s*[:=]\s*[\"']?)(?!{re.escape(REDACTED)})[^\s\"',;&}}]+"
        ),
        rf"\1{REDACTED}",
    ),
    # user:password@ in URLs and connection strings
    (re.compile(r"(?i)(\b[a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@"), rf"\1{REDACTED}@"),
    # JSON web tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"), REDACTED),
    # Cloud and code-hosting keys with a fixed prefix
    (re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b"), REDACTED),
    (re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,})"), REDACTED),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), REDACTED),
)


def redact(text: str) -> str:
    """``text`` with every recognised secret replaced by ``[redacted]``."""
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text
