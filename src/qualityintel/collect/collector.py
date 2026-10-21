"""Collect completed CI pipeline executions into history (docs/collection.md).

For every producer: list the workflow's completed runs on its branch, skip attempts collected
before, download each job's artifact, import the one path the producers file names with the
existing importers, and store the runs together with a :class:`PipelineCollection` record in
one transaction. A run whose artifacts are missing, expired or unreadable is still recorded,
as incomplete with its problems, so nothing disappears silently and nothing is retried
forever. Problems of one job never stop the other jobs or producers.
"""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from qualityintel.collect.archive import ArchiveError, unpack
from qualityintel.collect.config import JobSource, Producer, ProducersConfig
from qualityintel.collect.github import Artifact, CiSource, CollectError, WorkflowRun
from qualityintel.history.store import HistoryError, HistoryStore
from qualityintel.ingest.allure import is_allure_folder
from qualityintel.ingest.batch import expand_inputs, import_pipeline
from qualityintel.models.collection import PipelineCollection
from qualityintel.models.results import RunContext
from qualityintel.traceability.pipelines import PipelineState, pipeline_execution


@dataclass
class ProducerOutcome:
    """What one collection pass did for one producer."""

    repository: str
    workflow: str = ""
    seen: int = 0
    already_collected: int = 0
    collected: list[PipelineCollection] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def pipeline_id(producer: Producer, run: WorkflowRun) -> str:
    """``<repository name>#<run id>``: readable, and unique because run ids are."""
    return f"{producer.name}#{run.id}"


def collect(
    config: ProducersConfig,
    source: CiSource,
    store: HistoryStore,
    since: datetime,
    repositories: Sequence[str] = (),
    now: datetime | None = None,
) -> list[ProducerOutcome]:
    """One collection pass over every producer (or the ``repositories`` named)."""
    outcomes = []
    for producer in config.producer:
        if repositories and producer.repository not in repositories and producer.name not in repositories:
            continue
        outcome = ProducerOutcome(producer.repository, producer.workflow)
        outcomes.append(outcome)
        try:
            runs = source.completed_runs(producer.repository, producer.workflow, producer.branch, since)
        except CollectError as error:
            outcome.errors.append(str(error))
            continue
        for run in sorted(runs, key=lambda r: (r.started_at or since, r.id)):
            if producer.since is not None and (run.started_at is None or run.started_at < producer.since):
                continue  # predates the producer's publishing contract: neither seen nor incomplete
            outcome.seen += 1
            if store.is_collected(pipeline_id(producer, run), run.attempt):
                outcome.already_collected += 1
                continue
            try:
                outcome.collected.append(_collect_run(producer, run, source, store, now or datetime.now(UTC)))
            except (CollectError, HistoryError) as error:
                outcome.errors.append(f"run {run.id}: {error}")
    return outcomes


def _collect_run(
    producer: Producer, run: WorkflowRun, source: CiSource, store: HistoryStore, now: datetime
) -> PipelineCollection:
    """Download, import and store one run attempt; problems become part of the record."""
    pid = pipeline_id(producer, run)
    problems: list[str] = []
    workdir = Path(tempfile.mkdtemp(prefix="qi-collect-"))
    try:
        artifacts = {a.name: a for a in source.artifacts(producer.repository, run.id)}
        inputs: dict[str, list[str]] = {}
        for job in producer.job:
            found = _job_input(producer, job, artifacts.get(job.artifact), source, workdir, problems)
            if found is not None:
                inputs[job.name] = [str(found)]
        contexts: dict[str, RunContext] = {}
        for job in producer.job:
            values = producer.job_context(job).model_dump()
            values["build"] = values.get("build") or run.commit
            contexts[job.name] = RunContext.model_validate(values)
        batch = import_pipeline(
            inputs,
            pid,
            attempt=run.attempt,
            branch=run.branch,
            commit=run.commit,
            job_contexts=contexts,
            repository=producer.repository,
        )
        problems += [str(error) for error in batch.errors]
        # Files without a timestamp (Surefire, JUnit 5, Cucumber, k6, node:test) take the start
        # of the CI run, so they sort, filter by date and count as latest correctly
        runs = [
            r if r.started_at is not None else r.model_copy(update={"started_at": run.started_at})
            for r in batch.runs
        ]
        execution = pipeline_execution(runs, pid, [job.name for job in producer.job])
        # Missing jobs are already named by the artifact problems; keep each reason once
        named = _named(problems)
        problems += [
            p
            for p in execution.problems
            if not any(f": job {j} " in p for j in named)
            and not (problems and p.endswith("no runs of this pipeline were read"))  # says nothing new
        ]
        record = PipelineCollection(
            pipeline_id=pid,
            attempt=run.attempt,
            repository=producer.repository,
            workflow=producer.workflow,
            run_number=run.run_number,
            event=run.event,
            branch=run.branch,
            commit=run.commit,
            conclusion=run.conclusion,
            url=run.url,
            started_at=run.started_at,
            collected_at=now,
            state="complete" if execution.state is PipelineState.COMPLETE and not problems else "incomplete",
            runs=len(runs),
            results=sum(len(r.results) for r in runs),
            problems=tuple(dict.fromkeys(problems)),
        )
        store.add_collection(record, runs)
        return record
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _job_input(
    producer: Producer,
    job: JobSource,
    artifact: Artifact | None,
    source: CiSource,
    workdir: Path,
    problems: list[str],
) -> Path | None:
    """The unpacked path of one job's results, or ``None`` with the reason added to ``problems``."""
    if artifact is None:
        problems.append(
            f"job {job.name}: artifact {job.artifact} not found (job not run, cancelled or failed early)"
        )
        return None
    if artifact.expired:
        problems.append(f"job {job.name}: artifact {job.artifact} has expired")
        return None
    try:
        archive = source.download(producer.repository, artifact, workdir / f"{job.name}.zip")
        unpack(archive, workdir / job.name, keep=lambda name: _wanted(job.path, name))
    except CollectError as error:
        if error.transient:
            raise  # nothing is recorded; the next pass tries the run again
        problems.append(f"job {job.name}: {error}")
        return None
    except ArchiveError as error:
        problems.append(f"job {job.name}: {error}")
        return None
    path = (workdir / job.name / job.path).resolve()
    if not path.exists():
        problems.append(f"job {job.name}: {job.path} is not in artifact {job.artifact}")
        return None
    formats = _formats(path)
    if len(formats) > 1:
        problems.append(
            f"job {job.name}: {job.path} holds {' and '.join(sorted(formats))} results; name one of them "
            "in the producers file so the execution is not counted twice"
        )
        return None
    return path


def _wanted(path: str, member: str) -> bool:
    """Members under the job's path, without Allure attachments (the importer never reads them)."""
    inside = path in (".", "") or member == path or member.startswith(path.rstrip("/") + "/")
    return inside and "-attachment." not in member.rsplit("/", 1)[-1]


def _formats(path: Path) -> set[str]:
    """Result formats an input would be read as (an Allure folder is one Allure run)."""
    if path.is_file() or is_allure_folder(path):
        return {"one"}
    found = set()
    files, _ = expand_inputs([path])
    for file, _name in files:
        if is_allure_folder(file):
            found.add("Allure")
        elif file.suffix.lower() == ".xml":
            found.add("JUnit XML")
        else:
            found.add("mochawesome")
    return found


def _named(problems: list[str]) -> set[str]:
    """Job names that already have a problem (``job <name>: ...``)."""
    return {p.split(":", 1)[0].removeprefix("job ") for p in problems if p.startswith("job ")}
