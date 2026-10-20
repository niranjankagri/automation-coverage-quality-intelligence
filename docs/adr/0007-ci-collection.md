# ADR 0007: Collect results from CI artifacts, by a pull from this repository

Status: Accepted (2026-10-20)

## Context

The platform read only committed sample files. Plan M1 asks for current results from the real
automation pipelines, without copying reports by hand, keeping pipeline id, job, attempt,
branch and commit, never counting one execution twice, and never letting a missing job pass a
gate.

The producers already upload their reports as GitHub Actions artifacts, each job its own.
Formats differ (JUnit XML, mochawesome HTML, Allure results), and some jobs upload one
execution in two formats.

## Decision

- **Pull, not push.** A scheduled workflow in this repository lists the producers' completed
  runs and downloads their artifacts through the GitHub API. The producer repositories change
  nothing and hold no credentials for this platform.
- **A declared contract** (`config/producers.toml`): per job one artifact and one path. Exactly
  one representation of each execution is read; a path holding several formats is refused.
- **The existing importers and pipeline model** do the reading (`import_pipeline`,
  `pipeline_execution`); collection only downloads, unpacks safely and records.
- **A collection record per pipeline attempt**, stored with its runs in one transaction:
  conclusion, state, problems. It makes collection idempotent, keeps failed and cancelled runs
  distinguishable, and makes missing reports visible. Transient failures (network, token, rate
  limits) are not recorded, so the run is tried again.
- **Standard library only** for HTTP (`urllib`): no new dependency for four API calls.

## Alternatives considered

- **Producers push to an ingestion endpoint (webhook).** Needs a hosted, authenticated
  endpoint and a secret in every producer repository; it comes with M3 at the earliest, and the
  pull keeps working with no change in the producers.
- **`workflow_run` triggers.** They only fire for workflows of the same repository.
- **Import everything an artifact contains.** Counted the enterprise tests twice (Allure and
  Surefire) or three times (Surefire's per-class copies).

## Consequences

- Results appear in history within a day without manual steps; on demand with `workflow_dispatch`.
- Artifact layouts are a contract: a producer that renames an artifact or moves its report
  shows up as "artifact not found" / "path not in artifact" in the audit, not as silently
  missing data.
- Until M3 the history lives in a workflow artifact (90 days, renewed daily).
