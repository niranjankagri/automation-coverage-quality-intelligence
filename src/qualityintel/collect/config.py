"""The producers file: which repositories' CI results are collected, and where each job's results are.

Example (config/producers.toml, docs/collection.md)::

    [[producer]]
    repository = "niranjankagri/python-pytest-framework"
    workflow = "ci.yml"
    branch = "main"
    context = { framework = "pytest", environment = "ci", platform = "linux" }

    [[producer.job]]
    name = "api"
    artifact = "report-api"          # name of the uploaded artifact
    path = "junit.xml"               # the one file or folder inside it to import

Every job names exactly one path. That is the publishing contract: a job that uploads the same
results twice (Surefire JUnit XML and Allure results of one execution) is read once, in the
format the file names, so nothing is counted twice. The jobs listed are the jobs a complete
pipeline execution must have.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path, PurePosixPath
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from qualityintel.models.results import RunContext

MAX_PRODUCERS_FILE_BYTES = 1024 * 1024
_REPOSITORY = r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
_NAME = Annotated[str, Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.()-]+$")]


class ProducersError(ValueError):
    """The producers file cannot be read or is invalid."""


class _Section(BaseModel):
    """Strict, immutable configuration section (unknown keys are errors)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class JobSource(_Section):
    """Where one job's results are: an artifact and a path inside it.

    Attributes:
        name: The job name in the pipeline execution (``api``, ``ui-chrome``).
        artifact: Name of the artifact the job uploads.
        path: File or folder inside the artifact, relative, ``/`` separated; ``.`` for the
            artifact itself (e.g. an artifact that is an ``allure-results`` folder).
        context: Run context for this job's results, added to the producer's context.
    """

    name: _NAME
    artifact: Annotated[str, Field(min_length=1, max_length=200)]
    path: Annotated[str, Field(min_length=1, max_length=300)]
    context: RunContext = RunContext()

    @field_validator("path")
    @classmethod
    def _inside_the_artifact(cls, value: str) -> str:
        """A relative path without ``..``: it may not point outside the unpacked artifact."""
        parts = PurePosixPath(value).parts
        if value.startswith(("/", "\\")) or ".." in parts or "\\" in value or re.match(r"^[A-Za-z]:", value):
            raise ValueError("must be a relative path inside the artifact, with / and without ..")
        return value


class Producer(_Section):
    """One repository's workflow and its jobs."""

    repository: Annotated[str, Field(pattern=_REPOSITORY)]
    workflow: Annotated[str, Field(min_length=1, max_length=200)]
    branch: Annotated[str, Field(min_length=1, max_length=200)] = "main"
    context: RunContext = RunContext()
    job: tuple[JobSource, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_jobs(self) -> Producer:
        """Job names identify jobs in the pipeline: each once."""
        names = [job.name for job in self.job]
        duplicates = sorted({n for n in names if names.count(n) > 1})
        if duplicates:
            raise ValueError(f"job names must be unique, repeated: {', '.join(duplicates)}")
        return self

    @property
    def name(self) -> str:
        """The repository name without its owner (``python-pytest-framework``)."""
        return self.repository.split("/", 1)[1]

    def job_context(self, job: JobSource) -> RunContext:
        """The producer's context with the job's values on top."""
        values = {k: v for k, v in self.context.model_dump().items() if v is not None}
        values.update({k: v for k, v in job.context.model_dump().items() if v is not None})
        return RunContext.model_validate(values)


class ProducersConfig(_Section):
    """All producers."""

    producer: tuple[Producer, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_workflows(self) -> ProducersConfig:
        """One entry per repository workflow, so each pipeline is collected once."""
        keys = [(p.repository, p.workflow) for p in self.producer]
        duplicates = sorted({f"{r} {w}" for r, w in keys if keys.count((r, w)) > 1})
        if duplicates:
            raise ValueError(f"each repository workflow once, repeated: {', '.join(duplicates)}")
        return self


def load_producers(path: Path) -> ProducersConfig:
    """Read and validate a producers file.

    Raises:
        ProducersError: Unreadable, too large, not TOML, or invalid (the message names the field).
    """
    try:
        if path.stat().st_size > MAX_PRODUCERS_FILE_BYTES:
            raise ProducersError(
                f"{path.name}: file is larger than the limit of {MAX_PRODUCERS_FILE_BYTES} bytes"
            )
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError) as error:
        raise ProducersError(f"{path.name}: cannot be read ({error})") from None
    except tomllib.TOMLDecodeError as error:
        raise ProducersError(f"{path.name}: not valid TOML ({error})") from None
    except RecursionError:
        raise ProducersError(f"{path.name}: nested too deeply to be a producers file") from None
    try:
        return ProducersConfig.model_validate(data)
    except ValidationError as error:
        first = error.errors()[0]
        where = ".".join(str(part) for part in first["loc"])
        raise ProducersError(f"{path.name}: {where}: {first['msg']}") from None
