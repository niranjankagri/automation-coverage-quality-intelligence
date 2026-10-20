# ADR 0006: Pipeline executions as a unit of decision

Status: Accepted (2026-10-20)

## Context

Real CI runs have several test jobs (the TaskBoard pipeline: API, three browsers, components).
A gate given "the result files that exist" cannot see a job that never reported. The sample
pipeline run 38842296207 was cancelled by a newer push: its Firefox job uploaded nothing, the
other 114 results all passed, and a typical gate would have released it.

## Decision

- A run can carry a **pipeline job** (pipeline id, job, attempt, branch, commit), given at
  import with `--pipeline` and `--job NAME=PATH`. It is stored in history (schema 3).
- A **pipeline execution** is assembled from the runs with one id. A job's highest attempt
  counts; the execution is complete only when every expected job reported at least one result
  and all jobs agree on branch and commit.
- The gate file lists the expected jobs (`[pipeline] jobs`). An incomplete execution is an
  **input problem**: the gate is incomplete (exit 3), the existing "never pass on missing
  input" path, not a new kind of verdict.
- In a pipeline gate every run of the execution counts; elsewhere the pipeline job is part of
  the snapshot key, so two jobs in the same context do not replace each other.
- History accepts one import per job attempt; other files for a stored job attempt are refused.

## Alternatives considered

- **Read job status from the CI system's API.** Would catch more (a job cancelled after writing a
  partial report), but ties the tool to one CI system and needs credentials in the gate job. The
  report-based rule works with any CI; the limit is documented.
- **Infer expected jobs from earlier executions.** A job added or removed in the pipeline would
  make old executions look incomplete or hide new gaps. Expected jobs are stated, not guessed.
- **A shared history database written by every job.** SQLite is single-writer and CI jobs run
  in parallel on different machines ([ADR 0003](0003-sqlite-first.md)); collecting artifacts in
  a final job is the common CI pattern anyway.

## Consequences

- A release can no longer be decided on part of a pipeline when the gate names its jobs.
- CI configuration names each job's artifact once (`--job name=folder`).
- The dashboard cannot know the expected jobs by itself; they are entered on the Pipelines page.
