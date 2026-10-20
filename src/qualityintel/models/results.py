"""Test executions: one :class:`TestRun` per imported result file, one :class:`TestResult` per test."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from qualityintel.models.enums import Outcome

# Failure texts (stack traces) can be very long; the framework's own report keeps the full text
MAX_FAILURE_TEXT = 4000


class _Frozen(BaseModel):
    """Base for result types: immutable and strict about unknown fields."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class FailureDetails(_Frozen):
    """Why a test did not pass (or why it was skipped).

    Attributes:
        message: One-line summary from the producer (``message`` attribute in JUnit XML).
        type: Exception or assertion type when the producer gives one.
        text: Body text, usually a stack trace, cut to ``MAX_FAILURE_TEXT`` characters.
    """

    message: str = ""
    type: str = ""
    text: Annotated[str, Field(max_length=MAX_FAILURE_TEXT)] = ""


class TestResult(_Frozen):
    """One execution of one test inside a run.

    Attributes:
        classname: Producer's grouping (Java class, Python module, Robot suite path); may be empty.
        suite: Name of the innermost test suite element the test came from.
        duration_seconds: Execution time; ``None`` when the producer did not record it.
        test_ids: Explicit test case ids written by the framework (JUnit property or ``[ID]``
            token in the name); used before pattern matching.
        retries: Extra attempts the framework made inside this run (e.g. Surefire reruns).
            A passed result with retries > 0 passed only after failing first.
    """

    __test__ = False  # not a pytest test class, despite the name

    name: Annotated[str, Field(min_length=1)]
    classname: str = ""
    suite: str = ""
    outcome: Outcome
    duration_seconds: Annotated[float, Field(ge=0)] | None = None
    timestamp: datetime | None = None
    failure: FailureDetails | None = None
    test_ids: tuple[str, ...] = ()
    retries: Annotated[int, Field(ge=0)] = 0

    @property
    def key(self) -> str:
        """Stable identity of the test across runs: ``classname::name`` (or ``name`` alone)."""
        return f"{self.classname}::{self.name}" if self.classname else self.name

    @property
    def passed_after_retry(self) -> bool:
        """True when the test passed only on a repeated attempt within the same run."""
        return self.outcome is Outcome.PASSED and self.retries > 0


class RunContext(_Frozen):
    """Where and on what a run executed; every field is optional because files rarely say.

    Values come from the import command (``--framework``, ``--environment`` ...) and, when the
    producer records them, from JUnit properties. Runs are only compared with each other when
    their contexts match (see docs/metrics.md, "comparable executions").
    """

    framework: str | None = None
    environment: str | None = None
    browser: str | None = None
    platform: str | None = None
    build: str | None = None


class PipelineJob(_Frozen):
    """The CI pipeline execution and job a run came from (docs/pipelines.md).

    One pipeline execution (a GitHub Actions run, a GitLab pipeline, a Jenkins build) usually
    has several jobs, and each job writes its own result files. Grouping them is what lets a
    gate refuse to decide on a pipeline whose jobs did not all report.

    Attributes:
        pipeline_id: Identifier of the pipeline execution (e.g. ``github.run_id``).
        job: Name of the job within the pipeline (``api``, ``ui-chrome``).
        attempt: Re-run number of the job; the highest attempt of a job replaces earlier ones.
        branch: Branch the pipeline ran on, if known.
        commit: Commit the pipeline tested, if known.
    """

    pipeline_id: Annotated[str, Field(min_length=1, max_length=200)]
    job: Annotated[str, Field(min_length=1, max_length=200)]
    attempt: Annotated[int, Field(ge=1)] = 1
    branch: str | None = None
    commit: str | None = None


class TestRun(_Frozen):
    """All results imported from one result file.

    Attributes:
        run_id: SHA-256 of the file content, so importing the same file twice is detectable.
        source: File name the run was imported from (no directory, to keep local paths private).
        started_at: Earliest timestamp found in the file, if any.
        pipeline: The pipeline job the run belongs to, when it was imported as part of one.
    """

    __test__ = False  # not a pytest test class, despite the name

    run_id: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    source: str
    context: RunContext = RunContext()
    started_at: datetime | None = None
    results: tuple[TestResult, ...]
    pipeline: PipelineJob | None = None

    def outcome_counts(self) -> dict[Outcome, int]:
        """Number of results per outcome; every outcome is present, zero when absent."""
        counts = Counter(result.outcome for result in self.results)
        return {outcome: counts.get(outcome, 0) for outcome in Outcome}
