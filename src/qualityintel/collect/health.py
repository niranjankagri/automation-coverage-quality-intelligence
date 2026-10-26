"""Operational resolution of incomplete collections without changing historical evidence."""

from collections.abc import Sequence

from qualityintel.models.collection import PipelineCollection


def recovered_workflows(
    records: Sequence[PipelineCollection],
) -> dict[tuple[str, int], PipelineCollection]:
    """Map an incomplete attempt to later successful complete evidence in its exact workflow.

    This does not recover missing executions or modify a record. A different repository,
    workflow or branch never resolves an alert. Unknown branches and unordered runs remain
    unresolved; collection time alone cannot establish execution order after a backfill.
    """
    complete: dict[tuple[str, str, str], list[PipelineCollection]] = {}
    for record in records:
        if record.state == "complete" and record.conclusion == "success" and record.branch:
            complete.setdefault((record.repository, record.workflow, record.branch), []).append(record)
    recovered = {}
    for record in records:
        if record.state != "incomplete" or not record.branch:
            continue
        for candidate in complete.get((record.repository, record.workflow, record.branch), []):
            later_attempt = candidate.pipeline_id == record.pipeline_id and candidate.attempt > record.attempt
            later_run = (
                candidate.pipeline_id != record.pipeline_id
                and record.started_at is not None
                and candidate.started_at is not None
                and candidate.started_at > record.started_at
                and candidate.run_number > record.run_number > 0
            )
            if later_attempt or later_run:
                recovered[(record.pipeline_id, record.attempt)] = candidate
                break
    return recovered
