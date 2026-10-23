"""Issue drafts for recurring failures, never created by this program (docs/issues.md).

A draft is a title and a Markdown body built from recorded executions only: the failure signature,
how often and how recently it was seen (the rank of docs/metrics.md), the affected tests and the
newest supporting runs with their links. When every supporting run belongs to one known repository,
the draft also carries a link to GitHub's own *New issue* form with title and body filled in. Opening
that link creates nothing: a person reads the draft and presses *Submit new issue* on GitHub, which is
the approval the plan asks for. The program holds no GitHub write access and makes no request.

Imported text (signatures, test names) is escaped for Markdown or kept in code spans, so a test
named ``[x](https://...)`` stays text in the issue.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote, urlencode

from qualityintel.history.analysis import RecurringFailure
from qualityintel.reporting.markdown import md, md_code

# GitHub answers 414 for very long addresses; stay well below its limit
MAX_URL = 7000
# Tests and runs a draft names at most (the counts cover all of them)
LISTED = 10


@dataclass(frozen=True)
class Evidence:
    """One supporting run: its file name, dashboard path and GitHub run, when known."""

    source: str
    started_at: datetime | None
    dashboard_path: str
    github_url: str | None


@dataclass(frozen=True)
class IssueDraft:
    """A suggested issue for one recurring failure.

    Attributes:
        repository: ``owner/name`` when every supporting run belongs to it, else ``None``.
        new_issue_url: GitHub's pre-filled *New issue* form, only with a single known repository.
        shortened: The body in the link lost evidence lines to fit the address length limit
            (the full body is in ``body``).
    """

    signature: str
    repository: str | None
    title: str
    body: str
    new_issue_url: str | None
    shortened: bool


def issue_draft(
    failure: RecurringFailure,
    repositories: Sequence[str | None],
    evidence: Sequence[Evidence],
    dashboard_url: str = "",
) -> IssueDraft:
    """The draft for one recurring failure; ``repositories`` of all its supporting runs."""
    known = {r for r in repositories}
    repository = next(iter(known)) if len(known) == 1 else None
    title = f"Recurring test failure: {failure.signature[:120]}"
    body = _body(failure, evidence, dashboard_url, LISTED)
    url, shortened = None, False
    if repository is not None:
        url = _new_issue_url(repository, title, body)
        listed = LISTED
        while len(url) > MAX_URL and listed > 0:
            listed -= 1
            shortened = True
            url = _new_issue_url(repository, title, _body(failure, evidence, dashboard_url, listed))
        if len(url) > MAX_URL:  # even without evidence lines: the copyable body is still there
            url, shortened = None, True
    return IssueDraft(failure.signature, repository, title, body, url, shortened)


def _new_issue_url(repository: str, title: str, body: str) -> str:
    """GitHub's New issue form for ``owner/name`` with title and body filled in."""
    owner, name = (quote(part, safe="") for part in repository.split("/", 1))
    return f"https://github.com/{owner}/{name}/issues/new?{urlencode({'title': title, 'body': body})}"


def _body(failure: RecurringFailure, evidence: Sequence[Evidence], dashboard_url: str, listed: int) -> str:
    """The issue body in Markdown; ``listed`` limits the tests and runs named."""
    seen = (
        f"{failure.first_seen:%Y-%m-%d} to {failure.last_seen:%Y-%m-%d} (UTC)"
        if failure.first_seen and failure.last_seen
        else "dates not recorded"
    )
    lines = [
        f"**Failure signature:** `{md_code(failure.signature)}`",
        "",
        f"Seen in **{failure.runs} runs** ({failure.recent_runs} in the 7 days before the newest run), "
        f"{failure.occurrences} occurrences, {seen}.",
        "",
        f"**Affected tests** ({len(failure.tests)}):",
        *(f"- `{md_code(test)}`" for test in failure.tests[:listed]),
    ]
    if len(failure.tests) > listed:
        lines.append(f"- and {len(failure.tests) - listed} more")
    lines += ["", f"**Newest supporting runs** ({failure.runs} in total):"]
    for item in evidence[:listed]:
        when = f"{item.started_at:%Y-%m-%d %H:%M} UTC" if item.started_at else "undated"
        links = (
            [f"[dashboard]({dashboard_url.rstrip('/')}/{item.dashboard_path.lstrip('/')})"]
            if dashboard_url
            else []
        )
        if item.github_url:
            links.append(f"[CI run]({item.github_url})")
        lines.append(f"- {md(item.source)}, {when}" + (f": {', '.join(links)}" if links else ""))
    lines += [
        "",
        "_Drafted by Quality Intelligence from recorded test executions; check the evidence before "
        "submitting. Ranking and signature rules: docs/metrics.md, Recurring failures._",
    ]
    return "\n".join(lines) + "\n"
