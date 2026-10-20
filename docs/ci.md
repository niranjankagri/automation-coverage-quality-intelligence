# Continuous integration

`.github/workflows/ci.yml` runs on every push and pull request. Every job must pass; the self gate
then decides on this repository's own release criteria ([pipelines.md](pipelines.md)).

| Job | Runner | What it checks |
|---|---|---|
| Lint, format, types | ubuntu-26.04 | ruff (incl. docstrings), ruff format, mypy `--strict` |
| Dependency audit | ubuntu-26.04 | `pip-audit` on every installed version ([security.md](security.md)) |
| Tests (Python 3.12, 3.13) | ubuntu-26.04 | unit and integration tests, branch coverage >= 90 % |
| Tests (Python 3.13, Windows) | windows-2025 | the same on Windows (the README starts with cmd.exe) |
| Tests (Python 3.13, latest runner image) | ubuntu-latest | the same on whatever image GitHub moves `ubuntu-latest` to next |
| Dashboard in Chromium | ubuntu-26.04 | browser tests (incl. WCAG checks with axe-core) and screenshots |
| Dashboard in firefox, webkit | ubuntu-26.04 | the same browser tests in the other two engines |
| Container image | ubuntu-26.04 | builds the Docker image, starts it on a sample history, `tools/smoke.py`, non-root user, JSON log |
| Quality gates (sample data) | ubuntu-26.04 | `qi gate` on the samples: each documented exit code |
| Self gate (acceptance criteria) | ubuntu-26.04 | `qi gate` on this run's own unit and e2e results, as one pipeline execution |
| Demonstration from a clean checkout | ubuntu-26.04, windows-2025 | `pip install -e .` and `python tools/demo.py` from a fresh checkout |

## Pinned for predictable runs

- **Runner images by version.** `ubuntu-latest` and `windows-latest` move to new images on
  GitHub's schedule; a pinned label changes only when this file does. One test job stays on
  `ubuntu-latest` as a canary, so a migration shows up there first, without breaking the rest.
- **Actions by commit SHA**, with the release as a comment
  (`actions/checkout@3d3c42e... # v7.0.1`). A tag can be moved to other code; a commit cannot.
- **Python packages by exact version** in `pyproject.toml` (and `pip-audit==2.10.1` in the audit
  job).

## The Ubuntu 26 migration (October 2026)

GitHub announced that `ubuntu-latest` moves to Ubuntu 26.04 from 19 October 2026. Checked on
20 October 2026:

- The jobs of this repository already ran on the new image: the job logs show
  `Image: ubuntu-26.04` (image versions 20261012.163 and 20261018.168) for every run sampled from
  that day, from run 39374640587 to run 39408094202, all successful. `windows-latest` resolved to
  `windows-2025-vs2026`.
- So the project, its tests, the browser tests and the demonstration are validated on Ubuntu
  26.04; the workflow now names that image (and `windows-2025`) instead of the moving labels.

## Updating a pin

1. Runner image: change the label (for example `ubuntu-26.04` to its successor) and check that
   every job passes; the canary job will usually have shown it already.
2. Action: look up the release's commit (`gh api repos/actions/checkout/commits/v7.0.2 -q .sha`),
   replace the SHA and the comment, run CI.
3. Python package: change the version in `pyproject.toml`, run the full suite and the audit job.
