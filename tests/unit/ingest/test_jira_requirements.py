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


def _with_description(description: dict[str, Any]) -> dict[str, Any]:
    """The fixture issue with another rich-text description."""
    item = issue()
    item["fields"]["description"] = description
    return item


def _fetch_one(tmp_path: Path, item: dict[str, Any], config: str = CONFIG) -> Any:
    """Fetch one issue through the real client with a fake opener."""
    (requirement,) = fetch_requirements(
        load_config(write_config(tmp_path, config)), ENV, Opener({"issues": [item], "isLast": True})
    )
    return requirement


def test_rich_text_keeps_formatted_words_in_their_sentence(tmp_path: Path) -> None:
    """Jira splits a sentence into text nodes at bold or links; they are joined as written, not by commas."""
    description = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Users "},
                    {"type": "text", "text": "must", "marks": [{"type": "strong"}]},
                    {"type": "text", "text": " log in with "},
                    {
                        "type": "text",
                        "text": "SSO",
                        "marks": [{"type": "link", "attrs": {"href": "https://sso"}}],
                    },
                    {"type": "text", "text": "."},
                ],
            },
            {"type": "paragraph", "content": [{"type": "text", "text": "Second paragraph."}]},
        ],
    }
    requirement = _fetch_one(tmp_path, _with_description(description))
    assert requirement.description == "Users must log in with SSO.\nSecond paragraph."


def test_rich_text_lists_and_line_breaks(tmp_path: Path) -> None:
    """Bullet and numbered list items get their own lines; a hard break is a line break."""

    def item_text(text: str) -> dict[str, Any]:
        """One list item holding one paragraph."""
        return {
            "type": "listItem",
            "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
        }

    description = {
        "type": "doc",
        "content": [
            {
                "type": "paragraph",
                "content": [
                    {"type": "text", "text": "Rules:"},
                    {"type": "hardBreak"},
                    {"type": "text", "text": "ask "},
                    {"type": "mention", "attrs": {"text": "@Ana"}},
                ],
            },
            {"type": "bulletList", "content": [item_text("card"), item_text("invoice")]},
            {"type": "orderedList", "content": [item_text("pay"), item_text("confirm")]},
        ],
    }
    requirement = _fetch_one(tmp_path, _with_description(description))
    assert requirement.description == "Rules:\nask @Ana\n- card\n- invoice\n1. pay\n2. confirm"


def test_long_description_is_shortened_not_rejected(tmp_path: Path) -> None:
    """A description over 4,000 characters no longer stops the sync: it is shortened with a visible note."""
    long_text = {
        "type": "doc",
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "x" * 5000}]}],
    }
    requirement = _fetch_one(tmp_path, _with_description(long_text))
    assert len(requirement.description) == 4000
    assert requirement.description.endswith("[... shortened; full text in Jira]")


def test_sample_config_maps_every_default_jira_priority(tmp_path: Path) -> None:
    """The shipped sample covers Jira's five default priorities, so none of them stops a sync."""
    sample = (Path(__file__).parents[3] / "samples" / "jira-sync.toml").read_text(encoding="utf-8")
    sample = sample.replace(
        'base_url = "https://example.atlassian.net"', 'base_url = "https://jira.example.test"'
    )
    sample = sample.replace('email_env = "QI_JIRA_EMAIL"', 'email_env = "JIRA_EMAIL"')
    sample = sample.replace('token_env = "QI_JIRA_API_TOKEN"', 'token_env = "JIRA_TOKEN"')
    expected = {"Highest": "p1", "High": "p2", "Medium": "p3", "Low": "p4", "Lowest": "p4"}
    for name, priority in expected.items():
        item = issue()
        item["fields"]["priority"] = {"name": name}
        item["fields"]["customfield_10042"] = {"value": "High"}
        requirement = _fetch_one(tmp_path, item, sample)
        assert requirement.priority is not None
        assert requirement.priority.value == priority, name
