"""What collection recorded about one attempt of one CI pipeline execution (docs/collection.md)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field


class PipelineCollection(BaseModel):
    """One collected attempt of a pipeline execution, whatever came of it.

    Kept also when nothing could be imported, so a cancelled run, an expired artifact or a
    broken report stays visible instead of silently missing from history.

    Attributes:
        pipeline_id: ``<repository name>#<run id>``, the id the imported runs carry.
        attempt: The CI system's re-run number.
        conclusion: What the CI system concluded (``success``, ``failure``, ``cancelled`` ...);
            independent of whether the results were complete.
        state: ``complete`` when every expected job reported results, else ``incomplete``.
        runs: Runs imported (0 when nothing could be read).
        results: Test results in those runs.
        problems: Why the collection is incomplete: missing artifacts, unreadable reports.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    pipeline_id: Annotated[str, Field(min_length=1, max_length=200)]
    attempt: Annotated[int, Field(ge=1)]
    repository: str
    workflow: str
    run_number: int = 0
    event: str = ""
    branch: str = ""
    commit: str = ""
    conclusion: str
    url: str = ""
    started_at: datetime | None = None
    collected_at: datetime
    state: Literal["complete", "incomplete"]
    runs: Annotated[int, Field(ge=0)] = 0
    results: Annotated[int, Field(ge=0)] = 0
    problems: tuple[str, ...] = ()
