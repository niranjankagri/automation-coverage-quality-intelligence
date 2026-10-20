"""Ingestion audit: what collection stored per repository over a period (docs/collection.md).

Built from the stored :class:`PipelineCollection` records, not from the last pass alone, so the
daily audit also shows repositories that had no new runs and incomplete collections of
earlier days.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime

from qualityintel.collect.collector import ProducerOutcome
from qualityintel.models.collection import PipelineCollection
from qualityintel.reporting.markdown import md


@dataclass
class RepositoryAudit:
    """Collection counts of one repository over the audit period."""

    repository: str
    pipelines: int = 0
    complete: int = 0
    incomplete: int = 0
    results: int = 0
    conclusions: Counter[str] = field(default_factory=Counter)
    latest: PipelineCollection | None = None
    problems: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def audit(
    records: Sequence[PipelineCollection],
    repositories: Sequence[str],
    since: datetime,
    outcomes: Sequence[ProducerOutcome] = (),
) -> list[RepositoryAudit]:
    """One row per configured repository (also those without collections) for runs since ``since``.

    Args:
        records: Stored collection records.
        repositories: The repositories of the producers file, in its order.
        since: Start of the period (pipeline start time; undated runs count as in the period).
        outcomes: The pass that just ran, for errors that produced no record (API failures).
    """
    rows = {repo: RepositoryAudit(repo) for repo in repositories}
    for record in records:
        if record.started_at is not None and record.started_at < since:
            continue
        row = rows.setdefault(record.repository, RepositoryAudit(record.repository))
        row.pipelines += 1
        row.complete += record.state == "complete"
        row.incomplete += record.state == "incomplete"
        row.results += record.results
        row.conclusions[record.conclusion] += 1
        if row.latest is None or (record.started_at or since) > (row.latest.started_at or since):
            row.latest = record
        row.problems += [f"{record.pipeline_id} attempt {record.attempt}: {p}" for p in record.problems]
    for outcome in outcomes:
        rows.setdefault(outcome.repository, RepositoryAudit(outcome.repository)).errors += outcome.errors
    return list(rows.values())


def render_text(rows: Sequence[RepositoryAudit], since: datetime) -> str:
    """Terminal version."""
    lines = [f"ingestion audit since {since.date().isoformat()}"]
    lines.append(
        f"  {'repository':<48} {'pipelines':>9} {'complete':>8} {'incompl.':>8} {'results':>8}  conclusions"
    )
    for row in rows:
        conclusions = ", ".join(f"{n} {c}" for c, n in sorted(row.conclusions.items())) or "-"
        lines.append(
            f"  {row.repository:<48} {row.pipelines:>9} {row.complete:>8} "
            f"{row.incomplete:>8} {row.results:>8}  {conclusions}"
        )
    for row in rows:
        for text in row.errors:
            lines.append(f"  ERROR {row.repository}: {text}")
        for text in row.problems[:20]:
            lines.append(f"  incomplete {row.repository}: {text}")
        if not row.pipelines and not row.errors:
            lines.append(f"  note {row.repository}: no completed pipeline in the period")
    return "\n".join(lines) + "\n"


def render_markdown(rows: Sequence[RepositoryAudit], since: datetime) -> str:
    """CI job summary version (every value escaped: names and problems come from outside)."""
    lines = [
        f"## Ingestion audit since {since.date().isoformat()}",
        "",
        "| Repository | Pipelines | Complete | Incomplete | Results | Conclusions | Latest |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        conclusions = ", ".join(f"{n} {c}" for c, n in sorted(row.conclusions.items())) or "-"
        latest = row.latest
        latest_text = (
            f"[#{latest.run_number}]({latest.url})"
            if latest and latest.url.startswith("https://github.com/")
            else "-"
        )
        lines.append(
            f"| {md(row.repository)} | {row.pipelines} | {row.complete} | {row.incomplete} | {row.results} "
            f"| {md(conclusions)} | {latest_text} |"
        )
    details = [(row, text, "error") for row in rows for text in row.errors]
    details += [(row, text, "incomplete") for row in rows for text in row.problems[:20]]
    if details:
        lines += ["", "**Problems**", ""]
        lines += [f"- {kind}: {md(row.repository)}: {md(text)}" for row, text, kind in details]
    return "\n".join(lines) + "\n"
