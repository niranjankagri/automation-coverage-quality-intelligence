"""Search across repositories, workflows, pipelines, tests, requirements and failure messages.

The index is built once per data snapshot (:func:`build_index`) from what the dashboard already
holds in memory; a query only filters it (:func:`search`), so typing never rescans the history.
Every entry names where it leads (a dashboard route with its parameters, and for pipelines the
GitHub run), the repositories it belongs to and when it was first and last seen, so a search can
be limited to a repository and a period.

Matching is literal and case-insensitive: every word of the query must occur in the entry's
text. Ranking, best first: the identifier equals the query, starts with it, contains it, then
only the other text matches; ties go to the most recently seen entry, then the identifier.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime

from qualityintel.models.catalog import Catalog
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.enums import Outcome
from qualityintel.models.results import TestRun

KINDS = ("repository", "workflow", "pipeline", "test", "requirement", "failure")
MIN_QUERY = 2
MAX_QUERY = 100
# A failure message is searched by its first line, at most this long (the full text is on the test page)
MESSAGE_CHARS = 300


@dataclass(frozen=True)
class Entry:
    """One searchable thing and where it leads.

    Attributes:
        kind: One of :data:`KINDS`.
        identifier: What it is called (repository name, pipeline id, test key, requirement id ...).
        title: A second line of text (workflow, requirement title, failure message ...).
        route: Dashboard route the result opens (``/test``, ``/pipelines`` ...).
        params: Route parameters (they keep the repository when the route needs it).
        repositories: Repositories it belongs to (empty: not tied to one, e.g. a requirement).
        first_seen: Earliest run or collection it appears in (``None``: not dated).
        last_seen: Latest run or collection it appears in.
        url: An external evidence link (the GitHub run of a pipeline), https only.
    """

    kind: str
    identifier: str
    title: str
    route: str
    params: tuple[tuple[str, str], ...] = ()
    repositories: frozenset[str] = frozenset()
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    url: str | None = None
    text: str = field(default="", compare=False)


@dataclass(frozen=True)
class SearchResults:
    """Matches grouped by kind: the shown entries (bounded) and the full count of each group."""

    query: str
    groups: dict[str, tuple[Entry, ...]]
    counts: dict[str, int]

    @property
    def total(self) -> int:
        """Matches over all groups (not only the shown ones)."""
        return sum(self.counts.values())


class QueryError(ValueError):
    """The query cannot be searched (too short or too long)."""


def build_index(
    catalog: Catalog, runs: Sequence[TestRun], collections: Sequence[PipelineCollection]
) -> tuple[Entry, ...]:
    """Every searchable entry of one snapshot."""
    entries: list[Entry] = []
    seen: dict[tuple[str, str], _Span] = {}

    def note(kind: str, identifier: str, repository: str | None, when: datetime | None) -> _Span:
        span = seen.setdefault((kind, identifier), _Span())
        span.add(repository, when)
        return span

    workflows: dict[tuple[str, str], _Span] = {}
    for record in collections:
        when = record.started_at or record.collected_at
        note("repository", record.repository, record.repository, when)
        workflows.setdefault((record.repository, record.workflow), _Span()).add(record.repository, when)
    pipelines: dict[str, tuple[_Span, PipelineCollection | None, str | None]] = {}
    for record in collections:
        span, best, repository = pipelines.get(record.pipeline_id, (_Span(), None, record.repository))
        span.add(record.repository, record.started_at or record.collected_at)
        latest = record if best is None or record.attempt > best.attempt else best
        pipelines[record.pipeline_id] = (span, latest, repository)

    tests: dict[str, tuple[_Span, str]] = {}
    failures: dict[tuple[str, str], _Span] = {}
    for run in runs:
        repository = run.pipeline.repository if run.pipeline else None
        if repository:
            note("repository", repository, repository, run.started_at)
        if run.pipeline and run.pipeline.pipeline_id not in pipelines:
            pipelines[run.pipeline.pipeline_id] = (_Span(), None, repository)
        if run.pipeline:
            pipelines[run.pipeline.pipeline_id][0].add(repository, run.started_at)
        for result in run.results:
            span, name = tests.get(result.key, (_Span(), result.name))
            span.add(repository, run.started_at)
            tests[result.key] = (span, name)
            if result.outcome in (Outcome.FAILED, Outcome.ERROR) and result.failure:
                lines = (result.failure.message or result.failure.text or "").strip().splitlines()
                if lines:
                    failures.setdefault((result.key, lines[0][:MESSAGE_CHARS]), _Span()).add(
                        repository, run.started_at
                    )

    for (kind, identifier), span in seen.items():
        entries.append(
            _entry(kind, identifier, "repository", "/pipelines", (("repository", identifier),), span)
        )
    for (repository, workflow), span in workflows.items():
        entries.append(
            _entry(
                "workflow",
                workflow,
                repository,
                "/pipelines",
                (("repository", repository), ("workflow", workflow)),
                span,
            )
        )
    for pipeline_id, (span, latest_record, repository) in pipelines.items():
        run_id = pipeline_id.rsplit("#", 1)[-1]
        title = (
            f"{latest_record.workflow} #{latest_record.run_number} · run {run_id}"
            if latest_record
            else f"run {run_id}"
        )
        where: tuple[tuple[str, str], ...] = (("pipeline", pipeline_id),)
        if repository:
            where = (*where, ("repository", repository))
        url = latest_record.url if latest_record and latest_record.url.startswith("https://") else None
        entries.append(_entry("pipeline", pipeline_id, title, "/pipelines", where, span, url))
    for key, (span, name) in tests.items():
        entries.append(_entry("test", key, name, "/test", (("key", key), *_repository_param(span)), span))
    for (key, first_line), span in failures.items():
        entries.append(
            _entry("failure", key, first_line, "/test", (("key", key), *_repository_param(span)), span)
        )
    for requirement in catalog.requirements:
        title = " · ".join(
            part for part in (requirement.title, requirement.feature, requirement.owner) if part
        )
        entries.append(
            _entry("requirement", requirement.id, title, f"/requirement/{requirement.id}", (), _Span())
        )
    return tuple(entries)


def search(
    index: Iterable[Entry],
    query: str,
    repositories: frozenset[str] = frozenset(),
    since: date | None = None,
    until: date | None = None,
    limit: int = 20,
) -> SearchResults:
    """Entries matching every word of ``query``, grouped and ranked; at most ``limit`` per group.

    Raises:
        QueryError: The query is shorter than :data:`MIN_QUERY` or longer than :data:`MAX_QUERY`.
    """
    text = " ".join(query.split())
    if len(text) < MIN_QUERY:
        raise QueryError(f"search needs at least {MIN_QUERY} characters")
    if len(text) > MAX_QUERY:
        raise QueryError(f"search takes at most {MAX_QUERY} characters")
    words = text.lower().split()
    matches: dict[str, list[tuple[tuple[int, float, str], Entry]]] = {kind: [] for kind in KINDS}
    for entry in index:
        if not all(word in entry.text for word in words):
            continue
        if repositories and entry.repositories and not entry.repositories & repositories:
            continue
        if not _in_period(entry, since, until):
            continue
        matches[entry.kind].append((_rank(entry, text.lower()), entry))
    groups = {
        kind: tuple(e for _, e in sorted(found, key=lambda x: x[0])[:limit])
        for kind, found in matches.items()
    }
    return SearchResults(
        query=text, groups=groups, counts={kind: len(found) for kind, found in matches.items()}
    )


@dataclass
class _Span:
    """Repositories and the first and last time something was seen."""

    repositories: set[str] = field(default_factory=set)
    first: datetime | None = None
    last: datetime | None = None

    def add(self, repository: str | None, when: datetime | None) -> None:
        if repository:
            self.repositories.add(repository)
        if when is not None:
            self.first = when if self.first is None or when < self.first else self.first
            self.last = when if self.last is None or when > self.last else self.last


def _entry(
    kind: str,
    identifier: str,
    title: str,
    route: str,
    params: tuple[tuple[str, str], ...],
    span: _Span,
    url: str | None = None,
) -> Entry:
    return Entry(
        kind=kind,
        identifier=identifier,
        title=title,
        route=route,
        params=params,
        repositories=frozenset(span.repositories),
        first_seen=span.first,
        last_seen=span.last,
        url=url,
        text=f"{identifier}\n{title}".lower(),
    )


def _repository_param(span: _Span) -> tuple[tuple[str, str], ...]:
    """Keep the repository context in a link when the entry belongs to exactly one."""
    return (("repository", next(iter(span.repositories))),) if len(span.repositories) == 1 else ()


def _in_period(entry: Entry, since: date | None, until: date | None) -> bool:
    """Undated entries (requirements) always; dated ones when they were seen in the period."""
    if entry.first_seen is None or entry.last_seen is None:
        return True
    if since is not None and entry.last_seen.date() < since:
        return False
    return not (until is not None and entry.first_seen.date() > until)


def _rank(entry: Entry, query: str) -> tuple[int, float, str]:
    identifier = entry.identifier.lower()
    if identifier == query:
        level = 0
    elif identifier.startswith(query):
        level = 1
    elif query in identifier:
        level = 2
    else:
        level = 3
    recency = -(entry.last_seen.timestamp() if entry.last_seen else 0.0)
    return (level, recency, entry.identifier)
