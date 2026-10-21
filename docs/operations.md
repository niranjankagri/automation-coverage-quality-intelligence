# Operations

How to run the dashboard for other people: choosing who can see it, keeping its data, backing
it up, watching it, and what to do when something goes wrong. The protections themselves are in
[security.md](security.md).

## Who can see it

| Mode | Settings | For |
|---|---|---|
| This machine only (default) | `QI_DASHBOARD_HOST=127.0.0.1` | one person |
| Private, shared | `QI_DASHBOARD_PASSWORD` (12+ characters), TLS in front | a team, internal results |
| Public demonstration | `QI_DASHBOARD_PUBLIC=true`, TLS in front | data that is public anyway |

`qi dashboard` refuses any address other than this machine unless one of the last two is chosen.
**Public mode is only for public data**: the demonstration shows results collected from public
GitHub repositories, whose CI logs anyone can already read. Never use it for internal results;
everything imported is readable by anyone who can reach the page (requirement texts, test names,
failure messages, commit and branch names).

Behind a proxy or a platform's ingress set `QI_FORWARDED_ALLOW_IPS` to the proxy's address (or
`*` when only the proxy can reach the port), so the login lock-out sees real client addresses and
the page sends HSTS over https. `qi config` shows the mode in effect; it never prints the password.

## Retention

```text
qi history prune --keep-days 365 --database .qi/quality.db
```

deletes runs (with their results), collection records and coverage snapshots that started more
than N days ago, keeping the latest snapshot of each catalog, and compacts the file so the
deleted text is gone from it. `--keep-days` must be at least 91: `qi collect` looks back up to
90 days and would otherwise import the pruned pipelines again. Suggested: 365 days for a team
(trends over a year), shorter if failure messages may hold sensitive text.

## Backup and restore

```text
qi history backup backups/quality-2026-10-21.db --database .qi/quality.db
qi history check --database backups/quality-2026-10-21.db
qi history restore backups/quality-2026-10-21.db --database .qi/quality.db --replace
```

- `backup` uses SQLite's online backup, so it is consistent while the dashboard or a collection
  is using the file; it never overwrites a file, and verifies the copy (integrity check, same
  number of runs and results) before reporting success.
- `check` verifies any file without creating or changing it: SQLite's integrity check, foreign
  keys, schema version, contents.
- `restore` checks the backup first, refuses to overwrite an existing database without
  `--replace`, and swaps the file in with one rename (the database is either the old or the
  restored file, never half of each).
- Restore drills are part of the tests (`tests/unit/test_cli_history.py`). Store backups like
  the database itself: whoever can read the file can read the history.

## Monitoring

| Signal | Where | Healthy |
|---|---|---|
| Liveness | `GET /api/health` | `200`, `"status": "ok"`, the expected numbers of requirements and runs |
| Freshness | `GET /api/status` | `stale: false`, `last_error: null`, `latest_collection_at` within `QI_COLLECTION_HOURS` |
| Collection | Collection page, `collect.yml` run page | every repository *on time*, no incomplete pipelines in 7 days |
| Data problems | `/api/status` `collection_problems`, the freshness bar | empty |

A failed reload keeps the last good data and marks it stale (the bar says so); the server never
shows a half-loaded state. The collection workflow fails when a producer cannot be read, so its
own run history is the alert.

**Alerts.** The daily *Live dashboard* workflow (08:30 UTC) fails when the site is down, cannot
reload, its latest collection is older than 30 hours, or 3 or more collections in 7 days were
incomplete; every failed check prints what to look at. A failed workflow run is e-mailed by
GitHub to the repository owner (for a scheduled run, the user who last changed its schedule),
according to the owner's notification settings for Actions. To test that the alert arrives, run
the workflow by hand with `max_collection_age` 0.01: it fails on purpose.

## Recovery drills (2026-10-21)

Run on the real history and the live site; the commands and tests are in the repository.

| Drill | Result |
|---|---|
| New data while the site runs (publication 03:09 UTC, site kept busy) | swapped in by the hourly fetch at 04:07:45 UTC without a restart: 72 → 74 pipelines |
| Site left alone 17 and 35 minutes (free plan) | no spin-down observed: same instance, first request 0.4 s; a cold start could not be measured |
| Import killed at 2, 3, 4, 5 and 6 s | integrity ok, no orphan results, no half-written run (also `tests/integration/test_interrupted_import.py`) |
| Download cut at 50 %, 90 %, 99.9 % | refused; the old database stayed |
| Backup, 64 KB of the original overwritten, restore | damage detected (exit 3, after a fix: it used to crash), restore refused without `--replace`, restored with it; 250 runs, 29,898 results before and after |

## Incidents

1. **The page shows stale data.** Look at `/api/status` (`last_error`), then the latest
   *Collect CI results* run. A database that cannot be read: `qi history check`; restore the
   latest good backup.
2. **A secret appears in a failure message.** Redaction covers common shapes only
   ([security.md](security.md)). Remove the run (`HistoryStore.remove` or prune), rotate the
   secret where it belongs, fix the test that printed it, and re-collect.
3. **The password may be known to someone who should not have it.** Set a new
   `QI_DASHBOARD_PASSWORD` and restart; basic authentication has no sessions to revoke.
4. **Many 429 answers.** Someone is guessing the password (or a proxy hides client addresses:
   check `QI_FORWARDED_ALLOW_IPS`). The lock-out lasts at most 5 minutes per address.
5. **A vulnerability report.** See [SECURITY.md](../SECURITY.md) (private reporting is on).

## Dependencies and secrets in the repository

- `pip-audit` checks every installed version on every push (CI job *Dependency audit*).
- Dependabot ([.github/dependabot.yml](../.github/dependabot.yml)) proposes updates of the pinned
  actions and Python packages once a month, grouped into one pull request each; security
  updates come as soon as an advisory is published.
- GitHub secret scanning with push protection is on: a commit containing a known token format
  is refused.
