# Deployment

Live: <https://quality-intelligence-0ur1.onrender.com> (Render, free plan, since 2026-10-21).

The public demonstration runs on Render's free plan from this repository. It shows the results
the daily collection gathers from the portfolio's public framework repositories, read against
the sample catalog. Operating it (modes, retention, backups, incidents) is described in
[operations.md](operations.md).

## How it fits together

```text
producer repositories ──(CI artifacts)──> collect.yml, daily 07:40 UTC
                                              │ qi collect, prune 365 days, verified backup
                                              ▼
                         release "history", asset quality.db (public, permanent)
                                              │ qi history fetch: at start, then hourly
                                              ▼
            Render web service (Docker, free) ──> https://<service>.onrender.com
                                              ▲
                     live.yml, daily 08:30 UTC: tools/smoke.py against the live address
                     deploy-smoke.yml, after CI passes on main: waits for the new commit, then
                     tools/smoke.py and tools/report_smoke.py (browser) against the live address
```

- **Data persistence.** The free service has no disk that survives a restart. The history's
  permanent home is the asset `quality.db` of the release `history`; the collection workflow
  restores it from there, adds the new pipelines, and publishes it again (only after a fully
  successful collection, and only a copy that passed `qi history check`). Each run also keeps
  the file as the workflow artifact `quality-history` (90 days), the fallback when the release
  is missing.
- **Start.** `deploy/start.sh` fetches the published history; without a valid one the service
  does not start (the platform retries), so it never shows an empty or half-written history.
  The fetch repeats every hour (`QI_FETCH_SECONDS`); a verified file is swapped in with one
  rename and the dashboard reloads by itself (it watches its sources). A failed fetch keeps
  the data the dashboard has.
- **Code deploys.** `render.yaml` deploys `main` only after the commit's CI checks passed
  (`autoDeployTrigger: checksPass`): a commit with a failing check is never deployed.
- **Health.** Render probes `/api/health`; the image also declares a Docker `HEALTHCHECK`.
- **Which commit runs.** `/api/health` reports `commit` (Render's `RENDER_GIT_COMMIT`, or
  `QI_BUILD_COMMIT`) and the footer shows it, so the deployment is traceable to its source.
- **Fast first page.** The default views are computed before a snapshot goes live, at start
  and after every refresh; time-independent analyses are kept per snapshot.
- **Logs.** `QI_ACCESS_LOG=json`: one JSON line per request (time, method, path, status, ms), no
  query strings, client addresses or headers.
- **Access.** Public mode (`QI_DASHBOARD_PUBLIC=true`): the data are results of public
  repositories. TLS comes from Render's proxy; `QI_FORWARDED_ALLOW_IPS=*` lets the dashboard see
  https (HSTS) and the client address (login lock-out, if a password is ever set).

## The image

`Dockerfile`: `python:3.13.14-slim-trixie`, pinned by digest; the package without development
tools; the sample catalog and nightly gate; a non-root user (uid 10001) that can write only
`/data`. `.dockerignore` admits only what the image needs. The CI job *Container image* builds
it on every push, starts it on a history of the sample runs and runs `tools/smoke.py` against
it, and checks the user and the JSON log.

Locally (Docker Desktop):

```text
docker build -t qi-dashboard .
docker run --rm -p 8000:10000 -e PORT=10000 -e QI_HISTORY_URL=https://github.com/niranjankagri/automation-coverage-quality-intelligence/releases/download/history/quality.db qi-dashboard
python tools/smoke.py http://127.0.0.1:8000 --collected
```

## Setting it up (once)

1. Sign in at <https://render.com> with the GitHub account that owns this repository and allow
   Render to read it.
2. **New → Blueprint**, choose this repository; Render reads `render.yaml` and creates the
   service `quality-intelligence`. Approve.
3. Wait for the first deploy, open the address Render shows, and check it:
   `python tools/smoke.py https://<service>.onrender.com --wait 180 --collected`.
4. Give the address to the daily live check:
   `gh variable set QI_LIVE_URL --body https://<service>.onrender.com`.

No secret is needed: the service fetches a public file, and Render deploys from its own GitHub
connection.

## Limits of the free plan

- The service **sleeps after 15 minutes** without requests; the next visit waits about a
  minute while it starts (and fetches the history). The smoke test waits up to three minutes.
- 750 free instance hours a month: enough for one service running all the time.
- One instance; the login lock-out and the data are per instance, which is what this design
  assumes.

A paid plan (always on, a persistent disk) needs no change in the image: point `--database`
at the disk and keep the hourly fetch, or run the collection there.
