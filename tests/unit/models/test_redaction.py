import pytest

from qualityintel.models.redaction import REDACTED, redact
from qualityintel.models.results import MAX_FAILURE_TEXT, FailureDetails

pytestmark = pytest.mark.unit

SECRETS = [
    ("Authorization: Bearer abc.def.ghi-123", "Authorization: [redacted]"),
    ('{"authorization": "Basic dXNlcjpwYXNz"}', '{"authorization": "[redacted]"}'),
    ("sent bearer 0123456789abcdef to /api", "sent Bearer [redacted] to /api"),
    ("login failed for password=hunter2&user=ava", "login failed for password=[redacted]&user=ava"),
    ('{"password": "s3cr3t!", "user": "ava"}', '{"password": "[redacted]", "user": "ava"}'),
    ("api_key: AbCdEf123456 rejected", "api_key: [redacted] rejected"),
    ("client-secret=xyz789;", "client-secret=[redacted];"),
    ("token=abc123 expired", "token=[redacted] expired"),
    ("GET https://ava:p4ss@db.example.com/x", "GET https://[redacted]@db.example.com/x"),
    ("jdbc:postgresql://admin:pw@host:5432/app", "jdbc:postgresql://[redacted]@host:5432/app"),
    (
        "jwt eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
        f"jwt {REDACTED}",
    ),
    ("key AKIAIOSFODNN7EXAMPLE used", f"key {REDACTED} used"),
    ("ghp_" + "a" * 36 + " leaked", f"{REDACTED} leaked"),
    ("-----BEGIN RSA PRIVATE KEY-----\nMIIE\n-----END RSA PRIVATE KEY-----", f"{REDACTED} private key"),
]

HARMLESS = [
    "AssertionError: expected 401 but was 200",
    "expected token count 3 but was 2",
    "the tokenizer failed on line 4",
    "Password field is required",
    "UI: authentication rejects an expired token and the user without a role",
    "GET https://shop.example.com/api/tasks?page=2 returned 500",
    "TimeoutException: Expected condition failed: waiting for element (tried for 10 second(s))",
]


@pytest.mark.parametrize(("text", "expected"), SECRETS)
def test_secrets_are_replaced(text: str, expected: str) -> None:
    """Each shape a secret takes in a failure message is caught; the rest stays readable."""
    assert redact(text) == expected


@pytest.mark.parametrize("text", HARMLESS)
def test_ordinary_messages_are_unchanged(text: str) -> None:
    """Words like token or password alone are not secrets."""
    assert redact(text) == text


def test_redaction_is_stable() -> None:
    """Redacting twice changes nothing more (history reloads go through the model again)."""
    once = redact("password=hunter2 Authorization: Bearer abcdefghijkl")

    assert redact(once) == once


def test_every_failure_is_redacted_and_stays_within_the_limit() -> None:
    """The model applies it to message and text; a longer replacement is cut back to the limit."""
    failure = FailureDetails(message="token=abc", text="x" * (MAX_FAILURE_TEXT - 6) + " pwd=a")

    assert failure.message == "token=[redacted]"
    assert len(failure.text) == MAX_FAILURE_TEXT
    assert "pwd=a" not in failure.text
