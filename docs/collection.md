# Collecting CI results

`qi collect` fetches the test results of other repositories' CI runs and stores each run as a
pipeline execution in history ([pipelines.md](pipelines.md)), with the existing importers. No
report is copied by hand; a scheduled workflow does it every day
([ADR 0007](adr/0007-ci-collection.md)).

```bash
export GITHUB_TOKEN=...            # downloading artifacts needs a token (listing does not)
qi collect --producers config/producers.toml --database .qi/quality.db --days 7
qi collect --audit-only            # no downloads: the ingestion audit of the database
qi gate --catalog quality/catalog.toml --config release.toml \
  --database .qi/quality.db --pipeline "cypress-typescript-framework#39403537526"
```

## The publishing contract (`config/producers.toml`)

A producer is one repository workflow. For each of its jobs the file names:

| Key | Meaning |
|---|---|
| `name` | the job name in the pipeline execution (`api`, `ui-chrome`) |
| `artifact` | the artifact the job uploads (`actions/upload-artifact` name) |
| `path` | the **one** file or folder inside the artifact that is imported: a JUnit XML file, a mochawesome report, or an `allure-results` folder (`.` when the artifact is that folder) |
| `context` | run context for the job (browser ...), added to the producer's `context` |

The jobs listed are the jobs a complete execution must have. The build of every collected run is
the commit it tested.

**No double counting.** Jobs often upload the same execution twice: the enterprise framework's
artifacts hold Allure results *and* Surefire XML (`TEST-TestSuite.xml`, per-class copies and
`testng-results.xml`). The contract names one path; if a named folder still holds several
formats, the job is refused with a problem ("holds Allure and JUnit XML results; name one of
them") instead of being read twice.

**Producers today** (layouts checked against real runs on 2026-10-20):

| Repository | Workflow | Jobs | Format |
|---|---|---|---|
| enterprise-test-automation-framework | `regression.yml` ("Main", every push) | unit, api, ui-chrome, smoke-edge | Allure |
| enterprise-test-automation-framework | `nightly.yml` | full-chrome, regression-edge, regression-firefox, grid-firefox | Allure |
| python-pytest-framework | `ci.yml` | api, ui-chromium, ui-firefox, ui-webkit | JUnit XML |
| cypress-typescript-framework | `ci.yml` | api, ui-chrome, ui-firefox, ui-edge, component | mochawesome HTML |
| robot-framework-automation | `ci.yml` | ui-chrome, ui-firefox | JUnit XML (`--xunit`) |

Not yet: **playwright-typescript-framework** uploads only Playwright blob reports (an internal
format, up to 271 MB per job). It needs `--reporter junit` output in its artifacts first.

## What one collection pass does

For every producer, for every **completed** run of its workflow on its branch since the start of
the day `--days` ago:

1. skip the run attempt if it was collected before (whatever came of it);
2. list the run's artifacts; for each job download its artifact (at most 150 MB), unpack only the
   configured path (Allure attachments, logs and screenshots are not written), check the path
   exists and holds one format;
3. import the jobs with `import_pipeline`: pipeline id `<repository name>#<run id>`, attempt =
   GitHub's `run_attempt`, branch, commit, job context;
4. store the runs **and** a collection record in one transaction.

The collection record keeps, per pipeline attempt: repository, workflow, run number, event,
branch, commit, **GitHub's conclusion** (`success`, `failure`, `cancelled` ...), run URL, start,
collection time, **state** (`complete` when every job reported results, else `incomplete`), runs,
results and **problems** (missing or expired artifacts, missing paths, unreadable reports). A
failed run with every report is complete with conclusion `failure`; a cancelled run with a
missing job is incomplete with conclusion `cancelled`: the two never look alike.

| Situation | Result |
|---|---|
| Same attempt collected again | skipped, nothing downloaded (idempotent) |
| Re-run of a run (attempt 2) | collected as its own attempt; a pipeline gate uses the job's latest attempt |
| Job's artifact missing (job cancelled, failed before upload) | recorded incomplete: "artifact X not found" |
| Artifact expired | recorded incomplete |
| Path missing in the artifact, broken zip, unreadable report | recorded incomplete, with the reason |
| Network error, token missing or not allowed, rate limit, GitHub server error | **nothing recorded**: the run is tried again next time; `qi collect` exits 3 |
| A producer cannot be listed | error for that producer; the others are still collected |

Exit codes: 0 when every producer could be read (incomplete pipelines are recorded, not errors),
3 when a producer or a run could not be read, 2 for wrong usage or an invalid producers file.

## Ingestion audit

Every pass prints, and with `--summary FILE` appends as Markdown, one row per configured
repository for the period: pipelines collected, complete, incomplete, results, conclusions,
link to the latest run, then every problem and error. A repository with no completed run in the
period is listed as such. In the scheduled workflow the audit is the job summary.

## Gates on collected pipelines

`qi gate --database DB --pipeline ID` decides on a collected pipeline. Its runs come from
history; when its latest collected attempt is incomplete, each recorded problem is an input
problem, so the gate is **incomplete (exit 3)** however its rules come out. A gate file with
`[pipeline] jobs` checks the job list as well.

## Security

Artifacts come from other repositories and are untrusted ([security.md](security.md)):

- zip members are checked before anything is written: no absolute paths, no `..`, no drive
  letters, no links; at most 5,000 files and 200 MB unpacked (checked against the declared sizes
  and again while writing, which stops zip bombs); downloads at most 150 MB;
- the token is read from `GITHUB_TOKEN` (or `GH_TOKEN`), sent only to `api.github.com`, never to
  the signed storage URL a download redirects to, and never part of a message;
- unpacked files are deleted after each run; imported failure messages are redacted as always;
- the producers file is strict: unknown keys (a stray `token = ...`) are errors, paths cannot
  leave the artifact.

## Token

Listing runs and artifacts of public repositories needs no token; downloading artifacts does
(GitHub answers 401 without one). The workflow passes `secrets.COLLECT_TOKEN` when it is set,
otherwise its own `github.token`. A fine-grained token with read access to the producers'
Actions is enough for `COLLECT_TOKEN`; it needs no write permission.

## History between runs

The database's permanent home is the asset `quality.db` of the release `history` in this
repository, which the hosted dashboard fetches ([deployment.md](deployment.md)). A run restores
it from there (or, when the release does not exist yet, from the artifact `quality-history` of
the last successful run, kept 90 days) and checks it with `qi history check`; after a fully
successful collection it prunes runs older than 365 days and publishes a verified copy again; if an earlier history exists but cannot be restored, the job
fails instead of starting an empty one. A partly failed collection uploads what it stored, but
the next run starts from the last successful history and collects those runs again, which is
safe because collection is idempotent.
