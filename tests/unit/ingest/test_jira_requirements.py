"""Jira Cloud requirement sync: config, field mapping, pagination and fail-closed behavior."""

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from qualityintel.ingest.jira_requirements import (
    JiraRequirementsError,
    fetch_requirements,
    load_config,
)

pytestmark = pytest.mark.unit

CONFIG = """
base_url = "https://jira.example.test"
jql = "project = SHOP ORDER BY key"
email_env = "JIRA_EMAIL"
token_env = "JIRA_TOKEN"
max_pages = 3

[fields]
id = "key"
title = "fields.summary"
description = "fields.description"
feature = "fields.components.0.name"
owner = "fields.assignee.displayName"
priority = "fields.priority.name"
criticality = "fields.customfield_10042.value"
risk = "fields.customfield_10043.value"
platforms = "fields.labels"

[values.criticality]
"High Impact" = "high"

[values.priority]
"Highest" = "p1"
"""
ENV = {"JIRA_EMAIL": "qa@example.test", "JIRA_TOKEN": "secret-token-value"}


class Response(io.BytesIO):
    """A response body usable in a with statement, like urllib's response."""


class Opener:
    """Return prepared Jira JSON pages and retain the requests for assertions."""

    def __init__(self, *answers: dict[str, Any] | BaseException) -> None:
        self.answers = list(answers)
        self.requests: list[urllib.request.Request] = []
        self.timeouts: list[float] = []

    def __call__(self, request: urllib.request.Request, timeout: float) -> Response:
        """Return the next response and remember its request timeout."""
        self.requests.append(request)
        self.timeouts.append(timeout)
        answer = self.answers.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return Response(json.dumps(answer).encode())


def write_config(tmp_path: Path, content: str = CONFIG) -> Path:
    """Write the fixture configuration."""
    path = tmp_path / "jira.toml"
    path.write_text(content, encoding="utf-8")
    return path


def issue(key: str = "SHOP-1", summary: str = "Checkout works") -> dict[str, Any]:
    """A Jira issue with nested, custom and rich-text fields."""
    return {
        "key": key,
        "fields": {
            "summary": summary,
            "description": {
                "type": "doc",
                "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Pay safely"}]}],
            },
            "components": [{"name": "Checkout"}],
            "assignee": {"displayName": "Shop team"},
            "priority": {"name": "Highest"},
            "customfield_10042": {"value": "High Impact"},
            "customfield_10043": {"value": "Medium"},
            "labels": ["web", "api"],
        },
    }


def test_config_maps_jira_fields_and_keeps_secrets_out_of_config(tmp_path: Path) -> None:
    """Config holds field paths, not credential values."""
    path = write_config(tmp_path)
    config = load_config(path)

    assert config.fields["id"] == "key"
    assert config.fields["criticality"] == "fields.customfield_10042.value"
    assert config.value_maps["priority"]["highest"] == "p1"
    assert config.email_env == "JIRA_EMAIL"


@pytest.mark.parametrize(
    ("replacement", "message"),
    [
        ('base_url = "http://jira.example.test"', "HTTPS URL"),
        ("max_pages = 101", "max_pages must be an integer"),
        ('email_env = "not a variable"', "environment variable name"),
    ],
)
def test_invalid_config_is_refused(tmp_path: Path, replacement: str, message: str) -> None:
    """Unsafe hosts and invalid limits or environment references fail before the request."""
    key = replacement.split(" = ", 1)[0]
    original = next(line for line in CONFIG.splitlines() if line.startswith(key + " = "))
    text = CONFIG.replace(original, replacement)
    with pytest.raises(JiraRequirementsError, match=message):
        load_config(write_config(tmp_path, text))


def test_search_maps_fields_uses_basic_auth_and_reads_adf(tmp_path: Path) -> None:
    """A single Jira issue maps to validated fields and credentials go only in the auth header."""
    config = load_config(write_config(tmp_path))
    opener = Opener({"issues": [issue()], "isLast": True})

    (requirement,) = fetch_requirements(config, ENV, opener)

    request = opener.requests[0]
    assert request.full_url == "https://jira.example.test/rest/api/3/search/jql"
    assert request.method == "POST"
    authorization = request.get_header("Authorization")
    assert authorization is not None
    assert authorization.startswith("Basic ")
    request_body = request.data
    assert isinstance(request_body, bytes)
    assert b"secret-token-value" not in request_body
    assert json.loads(request_body)["fields"] == [
        "assignee",
        "components",
        "customfield_10042",
        "customfield_10043",
        "description",
        "labels",
        "priority",
        "summary",
    ]
    assert opener.timeouts == [30]
    assert requirement.id == "SHOP-1"
    assert requirement.description == "Pay safely"
    assert requirement.feature == "Checkout"
    assert requirement.priority is not None
    assert requirement.priority.value == "p1"
    assert requirement.criticality is not None
    assert requirement.criticality.value == "high"
    assert requirement.platforms == ("web", "api")


def test_search_follows_all_pages_and_does_not_return_a_partial_result(tmp_path: Path) -> None:
    """Every nextPageToken is requested before the provider returns its requirements."""
    config = load_config(write_config(tmp_path))
    opener = Opener(
        {"issues": [issue("SHOP-1")], "nextPageToken": "page-2", "isLast": False},
        {"issues": [issue("SHOP-2")], "isLast": True},
    )

    requirements = fetch_requirements(config, ENV, opener)

    assert [item.id for item in requirements] == ["SHOP-1", "SHOP-2"]
    request_body = opener.requests[1].data
    assert isinstance(request_body, bytes)
    assert json.loads(request_body)["nextPageToken"] == "page-2"


def test_duplicate_pages_and_jira_warnings_fail_closed(tmp_path: Path) -> None:
    """Duplicate issue keys or JQL warnings cannot silently produce an incomplete catalog."""
    config = load_config(write_config(tmp_path))
    duplicate = Opener(
        {"issues": [issue()], "nextPageToken": "page-2", "isLast": False},
        {"issues": [issue()], "isLast": True},
    )
    with pytest.raises(JiraRequirementsError, match="duplicate issue key"):
        fetch_requirements(config, ENV, duplicate)

    warning = Opener({"issues": [], "warningMessages": ["unknown field"]})
    with pytest.raises(JiraRequirementsError, match="returned warnings"):
        fetch_requirements(config, ENV, warning)

    incomplete = Opener({"issues": [], "isLast": False})
    with pytest.raises(JiraRequirementsError, match="without a page token"):
        fetch_requirements(config, ENV, incomplete)


def test_page_limit_and_missing_credentials_fail_before_apply(tmp_path: Path) -> None:
    """A truncated API result or missing secret never yields syncable records."""
    config = load_config(write_config(tmp_path))
    with pytest.raises(JiraRequirementsError, match="set both JIRA_EMAIL and JIRA_TOKEN"):
        fetch_requirements(config, {"JIRA_EMAIL": "qa@example.test"}, Opener())

    config_text = CONFIG.replace("max_pages = 3", "max_pages = 1")
    limited = load_config(write_config(tmp_path, config_text))
    opener = Opener({"issues": [issue()], "nextPageToken": "page-2", "isLast": False})
    with pytest.raises(JiraRequirementsError, match="narrow the JQL"):
        fetch_requirements(limited, ENV, opener)


def test_http_errors_do_not_expose_credentials(tmp_path: Path) -> None:
    """Auth, permission and network failures are actionable without leaking the API token."""
    config = load_config(write_config(tmp_path))
    headers = Message()
    error = urllib.error.HTTPError("https://jira.example.test", 401, "unauthorized", headers, None)
    with pytest.raises(JiraRequirementsError, match="HTTP 401") as raised:
        fetch_requirements(config, ENV, Opener(error))
    assert "secret-token-value" not in str(raised.value)
