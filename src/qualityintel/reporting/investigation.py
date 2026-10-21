"""Copyable investigation summaries, as plain text and Markdown (docs/dashboard.md, Summaries).

Built only from the views the pages show, so the summary says exactly what the page says: the
observed outcomes, the counts, the evidence links and the limits of the data. It never states a
cause or a severity the data does not hold. The same input always gives the same text.

Imported text (test names, failure messages) is written as it is in plain text and escaped in
Markdown (``md``), so a test named ``[x](https://...)`` stays text. Failure messages were already
redacted on import (docs/security.md).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from qualityintel.models.enums import Outcome
from qualityintel.reporting.markdown import md
from qualityintel.workspace import BuildComparisonView, ExecutionView, TestHistory

# How many tests a comparison summary names per category before "and N more"
LISTED = 10
LIMITATIONS = (
    "Observations from imported CI reports only; no cause is inferred.",
    "A test that passed only on a retry is shown as passed when its report does not record the retry "
    "(Playwright JUnit output).",
)


@dataclass(frozen=True)
class Summary:
    """The same summary in two formats."""

    text: str
    markdown: str


def summarise_test(
    history: TestHistory, data_as_of: datetime | None, link: str | None = None, notice: str | None = None
) -> Summary:
    """One test: where it ran, its latest and previous outcome, its history in scope, evidence."""
    latest = history.executions[0]
    previous = history.executions[1] if len(history.executions) > 1 else None
    total = len(history.executions)
    other = total - history.passed - history.failed
    rows: list[tuple[str, str]] = [
        ("Test", history.key),
        *_where(latest),
        ("Latest outcome", _outcome(latest)),
        ("Previous outcome", _outcome(previous) if previous else "none in scope"),
        (
            "History in scope",
            f"{total} execution(s): {history.passed} passed, {history.failed} failed or errored, "
            f"{other} skipped",
        ),
        ("Stability", "; ".join(history.stability) if history.stability else "not classified"),
    ]
    if latest.failure:
        first_line = (latest.failure.message or latest.failure.type or "").splitlines()
        rows.append(("Latest failure", first_line[0][:300] if first_line else "(no message)"))
    rows.append(("Requirements", ", ".join(history.requirements) if history.requirements else "none linked"))
    evidence = [url for url in (latest.ci_url,) if url]
    return _render(f"Investigation: {history.key}", rows, evidence, data_as_of, link, notice)


def summarise_comparison(
    comparison: BuildComparisonView,
    data_as_of: datetime | None,
    link: str | None = None,
    notice: str | None = None,
) -> Summary:
    """Two builds: what changed where they ran the same suites, with counts and evidence links."""
    base, head = comparison.base, comparison.head
    rows: list[tuple[str, str]] = [
        ("Baseline build", f"{base.build}: {_counts(base.counts)}, pass rate {base.pass_rate.text}"),
        ("Comparison build", f"{head.build}: {_counts(head.counts)}, pass rate {head.pass_rate.text}"),
        (
            "Comparable suites",
            f"{len(comparison.compared_contexts)}: {', '.join(comparison.compared_contexts)}"
            if comparison.comparable
            else "none: the builds share no suite, nothing is compared",
        ),
    ]
    # The categories of the Compare page, in its order
    for category in (
        "newly failing",
        "recovered",
        "still failing",
        "newly flaky",
        "slower",
        "new test",
        "removed test",
    ):
        keys = [change.key for change in comparison.changes if change.category == category]
        if keys:
            shown = ", ".join(keys[:LISTED]) + (
                f" and {len(keys) - LISTED} more" if len(keys) > LISTED else ""
            )
            rows.append((f"{category.capitalize()} ({len(keys)})", shown))
    if comparison.only_in_base:
        rows.append(("Only in the baseline", ", ".join(comparison.only_in_base)))
    if comparison.only_in_head:
        rows.append(("Only in the comparison", ", ".join(comparison.only_in_head)))
    incomplete = [*base.incomplete_pipelines, *head.incomplete_pipelines]
    if incomplete:
        rows.append(("Incomplete pipelines", ", ".join(incomplete)))
    evidence = [*base.ci_runs, *head.ci_runs]
    return _render(
        f"Build comparison: {base.build} vs {head.build}", rows, evidence, data_as_of, link, notice
    )


def _where(execution: ExecutionView) -> list[tuple[str, str]]:
    """Repository, workflow, pipeline and job of an execution, and its context."""
    context = execution.context
    rows: list[tuple[str, str]] = []
    if execution.pipeline:
        pipeline = execution.pipeline
        if pipeline.repository:
            rows.append(("Repository", pipeline.repository))
        if execution.workflow:
            rows.append(("Workflow", execution.workflow))
        rows.append(("Pipeline", f"{pipeline.pipeline_id} attempt {pipeline.attempt}, job {pipeline.job}"))
    parts = [context.framework, context.environment, context.browser, context.platform]
    rows.append(("Context", " / ".join(part or "-" for part in parts) + f", build {context.build or '-'}"))
    return rows


def _outcome(execution: ExecutionView) -> str:
    when = f"{execution.started_at:%Y-%m-%d %H:%M} UTC" if execution.started_at else "time not recorded"
    retries = (
        f", after {execution.retries} retr{'y' if execution.retries == 1 else 'ies'}"
        if execution.retries
        else ""
    )
    return f"{execution.outcome.value} ({when}, build {execution.context.build or '-'}{retries})"


def _counts(counts: Mapping[Outcome, int]) -> str:
    return ", ".join(f"{n} {outcome.value}" for outcome, n in counts.items())


def _render(
    title: str,
    rows: Sequence[tuple[str, str]],
    evidence: Sequence[str],
    data_as_of: datetime | None,
    link: str | None,
    notice: str | None,
) -> Summary:
    as_of = f"{data_as_of:%Y-%m-%d %H:%M} UTC" if data_as_of else "unknown"
    limits = [*LIMITATIONS, *((notice,) if notice else ())]
    text_lines = [title, "", *(f"{name}: {value}" for name, value in rows)]
    md_lines = [
        f"### {md(title)}",
        "",
        "| | |",
        "|---|---|",
        *(f"| {md(name)} | {md(value)} |" for name, value in rows),
    ]
    if evidence:
        text_lines += ["", "Evidence:", *(f"- {url}" for url in evidence)]
        md_lines += ["", "**Evidence**", "", *(f"- <{url}>" for url in evidence)]
    if link:
        text_lines.append(f"Dashboard: {link}")
        md_lines += ["", f"[Open in the dashboard]({link})"]
    text_lines += ["", f"Data as of: {as_of}", "Limitations:", *(f"- {item}" for item in limits)]
    md_lines += ["", f"Data as of {as_of}.", "", "**Limitations**", "", *(f"- {md(item)}" for item in limits)]
    return Summary(text="\n".join(text_lines) + "\n", markdown="\n".join(md_lines) + "\n")
