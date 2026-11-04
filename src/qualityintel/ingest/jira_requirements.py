"""Read requirements from Jira Cloud's issue search API.

This module is intentionally read-only. It fetches issues with Jira's enhanced JQL search,
normalises configured fields into the requirement model and never sends an issue update.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tomllib
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from qualityintel.ingest.errors import IngestError
from qualityintel.ingest.requirements_csv import FIELD_ORDER, SYNC_GENERATED_MARKER
from qualityintel.models.catalog import Requirement

MAX_CONFIG_BYTES = 1024 * 1024
MAX_RESPONSE_BYTES = 10 * 1024 * 1024
MAX_PAGES = 100
PAGE_SIZE = 100
TIMEOUT_SECONDS = 30
# Requirement.description is LongText (at most 4,000 characters)
MAX_DESCRIPTION_CHARS = 4000
TRUNCATION_NOTE = " [... shortened; full text in Jira]"
_ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_FIELD_PATH = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\.[0-9]+)*$")
_REQUIREMENT_FIELDS = frozenset(FIELD_ORDER)
_ENUM_FIELDS = frozenset({"criticality", "priority", "risk"})


class JiraRequirementsError(IngestError):
    """A Jira configuration, request, or issue could not be imported safely."""


@dataclass(frozen=True)
class JiraRequirementsConfig:
    """Validated Jira connection and field mapping, without credentials."""

    base_url: str
    jql: str
    email_env: str
    token_env: str
    fields: Mapping[str, str]
    value_maps: Mapping[str, Mapping[str, str]]
    max_pages: int


Opener = Callable[[urllib.request.Request, float], Any]


def load_config(path: Path) -> JiraRequirementsConfig:
    """Read and validate the non-secret Jira sync configuration from TOML."""
    try:
        size = path.stat().st_size
        if size > MAX_CONFIG_BYTES:
            raise JiraRequirementsError(path.name, f"configuration exceeds {MAX_CONFIG_BYTES} bytes")
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except JiraRequirementsError:
        raise
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as error:
        raise JiraRequirementsError(path.name, f"cannot read configuration ({error})") from None
    if not isinstance(data, dict):
        raise JiraRequirementsError(path.name, "configuration must be a TOML table")
    unknown = sorted(
        set(data) - {"base_url", "jql", "email_env", "token_env", "fields", "values", "max_pages"}
    )
    if unknown:
        raise JiraRequirementsError(path.name, f"unknown setting(s): {', '.join(unknown)}")

    base_url = _required_text(data.get("base_url"), path.name, "base_url")
    parsed_url = urllib.parse.urlsplit(base_url)
    if (
        parsed_url.scheme != "https"
        or not parsed_url.hostname
        or parsed_url.username is not None
        or parsed_url.password is not None
        or parsed_url.query
        or parsed_url.fragment
    ):
        raise JiraRequirementsError(path.name, "base_url must be an HTTPS URL without credentials or query")
    base_url = base_url.rstrip("/")
    jql = _required_text(data.get("jql"), path.name, "jql")
    email_env = _env_name(data.get("email_env", "QI_JIRA_EMAIL"), path.name, "email_env")
    token_env = _env_name(data.get("token_env", "QI_JIRA_API_TOKEN"), path.name, "token_env")

    raw_fields = data.get("fields")
    if not isinstance(raw_fields, dict):
        raise JiraRequirementsError(path.name, "[fields] must map requirement fields to Jira field paths")
    unknown_fields = sorted(set(raw_fields) - _REQUIREMENT_FIELDS)
    if unknown_fields:
        raise JiraRequirementsError(path.name, f"unknown requirement field(s): {', '.join(unknown_fields)}")
    missing_fields = sorted({"id", "title"} - set(raw_fields))
    if missing_fields:
        raise JiraRequirementsError(path.name, f"[fields] must map: {', '.join(missing_fields)}")
    fields: dict[str, str] = {}
    for name, value in raw_fields.items():
        if not isinstance(value, str) or not _FIELD_PATH.fullmatch(value):
            raise JiraRequirementsError(path.name, f"fields.{name} must be a dotted Jira JSON field path")
        fields[name] = value

    raw_values = data.get("values", {})
    if not isinstance(raw_values, dict):
        raise JiraRequirementsError(path.name, "[values] must contain field mapping tables")
    if unknown := sorted(set(raw_values) - _ENUM_FIELDS):
        raise JiraRequirementsError(
            path.name, f"value mappings only support enum fields: {', '.join(unknown)}"
        )
    value_maps: dict[str, dict[str, str]] = {}
    for field, mapping in raw_values.items():
        if not isinstance(mapping, dict) or any(
            not isinstance(key, str) or not isinstance(value, str) for key, value in mapping.items()
        ):
            raise JiraRequirementsError(path.name, f"[values.{field}] must map text values to text values")
        value_maps[field] = {key.casefold(): value.casefold() for key, value in mapping.items()}

    max_pages = data.get("max_pages", MAX_PAGES)
    if type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES:
        raise JiraRequirementsError(path.name, f"max_pages must be an integer from 1 to {MAX_PAGES}")
    return JiraRequirementsConfig(base_url, jql, email_env, token_env, fields, value_maps, max_pages)


def fetch_requirements(
    config: JiraRequirementsConfig,
    environment: Mapping[str, str] | None = None,
    opener: Opener | None = None,
) -> list[Requirement]:
    """Fetch every matching Jira issue or fail without returning a partial result."""
    env = os.environ if environment is None else environment
    email = env.get(config.email_env, "").strip()
    token = env.get(config.token_env, "").strip()
    if not email or not token:
        raise JiraRequirementsError(
            "Jira credentials", f"set both {config.email_env} and {config.token_env} environment variables"
        )
    client = JiraIssueSearch(config, email, token, opener)
    return client.requirements()


class JiraIssueSearch:
    """Bounded Jira Cloud search client; credentials are sent only to the configured HTTPS host."""

    def __init__(
        self, config: JiraRequirementsConfig, email: str, token: str, opener: Opener | None = None
    ) -> None:
        self._config = config
        self._auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode("ascii")
        self._open = opener or _open_request
        self._fields = _jira_field_names(config.fields)

    def requirements(self) -> list[Requirement]:
        """Read search pages in order, rejecting incomplete, repeated, or malformed pages."""
        result: list[Requirement] = []
        seen_ids: set[str] = set()
        page_token: str | None = None
        seen_tokens: set[str] = set()
        for page_number in range(1, self._config.max_pages + 1):
            data = self._page(page_token)
            issues = data.get("issues")
            if not isinstance(issues, list) or any(not isinstance(issue, dict) for issue in issues):
                raise JiraRequirementsError("Jira search", "malformed response: issues must be an array")
            warnings = data.get("warningMessages", [])
            if not isinstance(warnings, list) or any(not isinstance(item, str) for item in warnings):
                raise JiraRequirementsError("Jira search", "malformed response: warningMessages must be text")
            if warnings:
                raise JiraRequirementsError(
                    "Jira search", "Jira returned warnings; fix the JQL before syncing"
                )
            for issue in issues:
                requirement = _requirement(issue, self._config)
                if requirement.id in seen_ids:
                    raise JiraRequirementsError("Jira search", f"duplicate issue key {requirement.id}")
                seen_ids.add(requirement.id)
                result.append(requirement)

            token = data.get("nextPageToken")
            is_last = data.get("isLast")
            if token is not None and (not isinstance(token, str) or not token):
                raise JiraRequirementsError("Jira search", "malformed response: nextPageToken must be text")
            if is_last is not None and type(is_last) is not bool:
                raise JiraRequirementsError("Jira search", "malformed response: isLast must be boolean")
            if is_last is False and token is None:
                raise JiraRequirementsError(
                    "Jira search", "Jira marked results incomplete without a page token"
                )
            if is_last is True or token is None:
                return result
            if token in seen_tokens:
                raise JiraRequirementsError(
                    "Jira search", "Jira repeated a page token; refusing partial results"
                )
            seen_tokens.add(token)
            page_token = token
            if page_number == self._config.max_pages:
                raise JiraRequirementsError(
                    "Jira search",
                    f"more than {self._config.max_pages} pages; narrow the JQL before applying a sync",
                )
        raise JiraRequirementsError("Jira search", "page limit reached; refusing partial results")

    def _page(self, page_token: str | None) -> dict[str, Any]:
        """Request and validate one Jira enhanced-search page."""
        path = "/rest/api/3/search/jql"
        payload: dict[str, object] = {
            "jql": self._config.jql,
            "maxResults": PAGE_SIZE,
            "fields": self._fields,
        }
        if page_token is not None:
            payload["nextPageToken"] = page_token
        request = urllib.request.Request(
            self._config.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "qualityintel",
                "Authorization": self._auth,
            },
            method="POST",
        )
        try:
            with self._open(request, TIMEOUT_SECONDS) as response:
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except urllib.error.HTTPError as error:
            hint = {
                401: "credentials are invalid",
                403: "the account cannot browse these issues",
                429: "rate limited",
            }
            detail = hint.get(error.code, "Jira request failed")
            raise JiraRequirementsError("Jira search", f"HTTP {error.code} ({detail})") from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            reason = getattr(error, "reason", None) or error
            raise JiraRequirementsError("Jira search", f"cannot reach Jira ({reason})") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise JiraRequirementsError("Jira search", f"response exceeds {MAX_RESPONSE_BYTES} bytes")
        try:
            data = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
            raise JiraRequirementsError("Jira search", "malformed JSON response") from None
        if not isinstance(data, dict):
            raise JiraRequirementsError("Jira search", "malformed JSON response: expected an object")
        return data


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward Jira authorization credentials to a redirect target."""

    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _open_request(request: urllib.request.Request, timeout: float) -> Any:
    """Open one request with the timeout in urllib's timeout parameter."""
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def _requirement(issue: dict[str, Any], config: JiraRequirementsConfig) -> Requirement:
    """Map one Jira issue into a validated quality-intelligence requirement."""
    data: dict[str, Any] = {}
    try:
        for name, path in config.fields.items():
            value = _at_path(issue, path)
            if value is None:
                continue
            rendered = _render_value(value)
            if rendered is None or rendered == "":
                continue
            if name in _ENUM_FIELDS:
                key = rendered.casefold()
                rendered = config.value_maps.get(name, {}).get(key, key)
            if name == "platforms":
                data[name] = [part.strip() for part in rendered.split(",") if part.strip()]
            elif name == "description" and len(rendered) > MAX_DESCRIPTION_CHARS:
                # Requirement descriptions hold at most 4,000 characters. A longer Jira description is
                # shortened, visibly, instead of failing the whole sync; Jira keeps the full text.
                keep = MAX_DESCRIPTION_CHARS - len(TRUNCATION_NOTE)
                data[name] = rendered[:keep].rstrip() + TRUNCATION_NOTE
            else:
                data[name] = rendered
        item = Requirement.model_validate(data)
    except (ValidationError, ValueError, TypeError, KeyError, IndexError) as error:
        identifier = issue.get("key")
        where = identifier if isinstance(identifier, str) else "an issue"
        if isinstance(error, ValidationError):
            first = error.errors()[0]
            field = ".".join(str(part) for part in first["loc"]) or "?"
            reason = f"{field}: {first['msg']}"
        else:
            reason = "configured field path could not be read"
        raise JiraRequirementsError("Jira search", f"{where}: {reason}") from None
    return item


def _at_path(value: Any, path: str) -> Any:
    """Read a dotted object path with numeric array indices, returning None for missing values."""
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            current = current.get(part)
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            current = current[index] if index < len(current) else None
        else:
            return None
        if current is None:
            return None
    return current


def _render_value(value: Any) -> str | None:
    """Convert Jira scalar, option, array, or Atlassian Document Format data to plain text."""
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, list):
        items = [rendered for item in value if (rendered := _render_value(item))]
        return ", ".join(items) if items else None
    if isinstance(value, dict):
        # Rich text (Atlassian Document Format) has its own rules: see _adf_text.
        if isinstance(value.get("type"), str) and ("content" in value or value["type"] == "text"):
            return _adf_text(value).strip() or None
        for key in ("value", "name", "displayName", "text"):
            if isinstance(value.get(key), (str, int, float)):
                return _render_value(value[key])
    return None


# ADF nodes that hold inline text: their children are joined without a separator, because Jira splits
# one sentence into several text nodes wherever formatting or a link changes ("Users " + bold "must" + ...).
_ADF_INLINE_PARENTS = frozenset({"paragraph", "heading", "codeBlock", "mediaSingle"})


def _adf_text(node: Any) -> str:
    """Plain text of an ADF node: inline text joined as written, block nodes on their own lines."""
    if not isinstance(node, dict):
        return ""
    kind = node.get("type")
    if kind == "text":
        text = node.get("text")
        return text if isinstance(text, str) else ""
    if kind == "hardBreak":
        return "\n"
    if kind in ("mention", "emoji", "status", "inlineCard"):
        attrs = node.get("attrs")
        if isinstance(attrs, dict):
            for key in ("text", "shortName", "url"):
                if isinstance(attrs.get(key), str):
                    return str(attrs[key])
        return ""
    content = node.get("content")
    if not isinstance(content, list):
        return ""
    parts = [_adf_text(child) for child in content]
    if kind in _ADF_INLINE_PARENTS:
        return "".join(parts)
    # Block containers (doc, lists, list items, quotes, panels, tables): one line per child block.
    lines = [part.strip("\n") for part in parts if part.strip()]
    if kind == "listItem":
        return " ".join(line.strip() for line in lines)
    if kind == "bulletList":
        lines = [f"- {line}" for line in lines]
    elif kind == "orderedList":
        lines = [f"{number}. {line}" for number, line in enumerate(lines, start=1)]
    return "\n".join(lines)


def _jira_field_names(fields: Mapping[str, str]) -> list[str]:
    """List top-level Jira fields needed by the mapping, excluding the top-level issue key."""
    names = sorted(
        {path.split(".", 1)[1].split(".", 1)[0] for path in fields.values() if path.startswith("fields.")}
    )
    return names


def _required_text(value: Any, source: str, name: str) -> str:
    """A non-empty TOML text setting."""
    if not isinstance(value, str) or not value.strip():
        raise JiraRequirementsError(source, f"{name} must be non-empty text")
    return value.strip()


def _env_name(value: Any, source: str, name: str) -> str:
    """Validate an environment variable name without reading its value."""
    if not isinstance(value, str) or not _ENV_NAME.fullmatch(value):
        raise JiraRequirementsError(source, f"{name} must be an environment variable name")
    return value


def render_requirements_toml(requirements: list[Requirement], source_name: str) -> str:
    """Render Jira results as the same generated-file format used by CSV import."""
    lines = [
        SYNC_GENERATED_MARKER,
        f"# from Jira configuration {source_name}; re-run `qi requirements sync` to update.",
        "# Test cases and their links to these requirements live in the catalog that includes this file.",
    ]
    for requirement in requirements:
        lines += ["", "[[requirement]]"]
        for name in FIELD_ORDER:
            value = getattr(requirement, name)
            if value is None or value == ():
                continue
            value = getattr(value, "value", value)
            serialized = json.dumps(
                list(value) if isinstance(value, tuple) else str(value), ensure_ascii=False
            )
            lines.append(f"{name} = {serialized}")
    return "\n".join(lines) + "\n"
