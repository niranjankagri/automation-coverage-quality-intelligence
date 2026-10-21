# Security and reliability

What the platform assumes, what it protects against, how each protection is checked, and what is
left to the people who run it. Reviewed on 2026-10-20 (Phase 7 of the post-1.0 plan) and for hosted operation on 2026-10-21
(M5); the findings and their fixes are listed at the end.

## Assumptions

- **Inputs are untrusted.** Result files, Allure folders, mochawesome reports, catalogs, CSV
  exports and gate files may come from any CI job, fork or person. They may be broken, huge or
  hostile.
- **The person running `qi` is trusted.** Command line options, environment variables and file
  paths are theirs; `qi` reads and writes only the paths they give.
- **The dashboard is read-only and holds everything that was imported.** Anyone who can open it
  can read every requirement, test name and failure message in it.
- **Network access only where asked for.** Only `qi collect` (the GitHub API) and
  `qi history fetch` (an https address given to it) use the network; nothing sends data
  anywhere. The dashboard loads nothing from other origins (only `/docs`, FastAPI's API
  documentation page, loads its scripts from a CDN).

## Protections

| Risk | Protection | Checked by |
|---|---|---|
| Entity expansion ("billion laughs"), external entities in XML | any DTD or entity declaration is refused before parsing, found by the XML parser itself in every encoding it reads (UTF-8, UTF-16 ...) | `tests/unit/ingest/test_hostile_input.py` |
| Broken or hostile files crashing the tool (deep nesting, wrong field types, odd encodings) | every importer turns such files into an input error naming the file: exit code 3, never 4, never a partial import | `test_hostile_input.py` |
| Huge files exhausting memory | size checked before reading: result files 50 MB, an Allure folder 50 MB in total, CSV and catalog 10 MB, gate files 1 MB; unknown file types refused | ingest unit tests, `test_hostile_input.py` |
| Imported text executed as code | no `eval`/`exec`/`compile`, no pickle-style loaders, no subprocesses anywhere in the package; TOML, JSON, CSV and XML are parsed as data only | `tests/architecture/test_no_code_execution.py` |
| Writes through the dashboard | the API has only GET routes; there is no upload | `test_api.py::test_the_api_accepts_no_writes` |
| Script injection in the dashboard | the front end writes every value as text (never `innerHTML`); strict Content-Security-Policy (no inline script, no other origins), `nosniff`, no referrer | API header tests, browser tests with hostile names |
| Script or link injection in reports | HTML reports escape every value and contain no scripts; Markdown summaries escape all Markdown punctuation, so a test named `[click](...)` or `<img ...>` shows as text | `tests/unit/gates/test_reports.py` |
| Unauthenticated access to the dashboard | listens on 127.0.0.1 by default; any other address is **refused** unless `QI_DASHBOARD_PASSWORD` is set, which turns on HTTP basic authentication for every path (constant-time comparison), or public mode is chosen explicitly (`QI_DASHBOARD_PUBLIC=true`, for public data only, with a warning) | `test_cli_dashboard.py`, `test_api.py`, browser test with a login |
| Password guessing | 10 wrong logins from one address within 5 minutes lock it out (429, `Retry-After`) until the count falls below the limit; memory bounded; client address from trusted proxies only (`QI_FORWARDED_ALLOW_IPS`) | `test_api.py::test_too_many_wrong_logins_lock_the_address_out_for_a_while`, `test_the_throttle_forgets_old_failures_and_stays_bounded` |
| Downgrade to http, cached private data | HSTS (one year) on every answer over https; API answers `private, no-store` with a login (`no-cache` without); `Permissions-Policy`, `frame-ancestors 'none'` | `test_api.py::test_api_answers_are_not_kept_by_caches_and_https_gets_hsts` |
| A tampered or broken published history | `qi history fetch` accepts https only (also after redirects), at most 200 MB, sends no credentials, and swaps the file in only after the integrity check passed; on any failure the old data stay | `tests/unit/history/test_fetch.py` |
| Data kept longer than needed, lost data | `qi history prune` (retention, compacts the file), `qi history backup` / `check` / `restore` with verification ([operations.md](operations.md)) | `test_cli_history.py`, `test_store.py` |
| Secrets in stored data and reports | test logs (`system-out`, `system-err`), attachments and environment dumps are never read; Allure `environment.properties` and JUnit properties are read through an allow-list; failure messages pass through a redaction of secret-shaped values (authorization headers, bearer tokens, `password=`/`token:`/`api_key` assignments, credentials in URLs, JWTs, AWS and GitHub keys, private keys) | `tests/unit/models/test_redaction.py`, sample hygiene tests |
| Secrets in the tool's own output | the dashboard password is never printed (`qi config` shows only whether it is set; it is left out of the settings' repr); uvicorn's access log is off | `test_config.py`, `test_cli_dashboard.py` |
| Hostile CI artifacts (collection) | zip members checked before writing: no absolute paths, `..`, drive letters, links, Windows-special names, duplicate paths or file/directory collisions; at most 10,000 entries, 5,000 files, 150 MB compressed and 200 MB unpacked; GitHub JSON responses at most 20 MB; only the configured path is unpacked; redirects require HTTPS; the token goes only to `api.github.com`, never to storage or messages | `tests/unit/collect/test_archive.py`, `test_github.py`, `test_collector.py` ([collection.md](collection.md#security)) |
| Path tricks in catalogs | `include` takes plain relative file names only (no `..`, no nesting) | catalog unit tests |
| Vulnerable dependencies, leaked secrets in commits | exact versions pinned; CI job *Dependency audit* runs `pip-audit` on every installed version on every push (none known on 2026-10-21); Dependabot security and monthly grouped updates; GitHub secret scanning with push protection | `.github/workflows/ci.yml`, `.github/dependabot.yml` |
| A gate passing on incomplete input | missing, unreadable or empty results and incomplete pipeline executions make the gate *incomplete* (exit 3) | gate and pipeline tests ([quality-gates.md](quality-gates.md), [pipelines.md](pipelines.md)) |

## Running the dashboard for a team

Modes, retention, backups, monitoring and incidents: [operations.md](operations.md).

1. Keep the default (`127.0.0.1`) for one person on one machine.
2. For a team, set a password of at least 12 characters in the environment, not in a file:
   `QI_DASHBOARD_PASSWORD` (and optionally `QI_DASHBOARD_USER`, default `qi`), then
   `qi dashboard --host 0.0.0.0 ...`.
3. Put TLS in front (a reverse proxy such as nginx or Caddy, or the platform's ingress): basic
   authentication sends the password with every request, readable on plain HTTP. `qi` reminds
   you of this when it serves on a non-loopback address.
4. Basic authentication is one shared login, not user management. For per-user access, single
   sign-on or audit logs, run the dashboard behind the organisation's authenticating proxy.

## Not covered (by design or not yet)

- **Redaction is a safety net, not a guarantee.** Secrets in unusual shapes (a bare token without
  a key name, a password inside prose) pass through. Test suites should not print secrets.
- **Test names and catalog text are shown as they are.** They are not redacted; they are
  identifiers chosen by the team.
- **The login lock-out is per process and per address.** A distributed guessing attack from
  many addresses is slowed only by the password's length; it is not a replacement for a
  proxy's or platform's own protection. Use a long random password.
- **CSV downloads** are made in the browser from what the API already returned; they contain
  nothing the page does not show, and cells a spreadsheet would run as formulas are made inert.
- **The history database is a plain SQLite file.** Anyone who can read the file can read the
  history; protect it with file permissions like any other build artifact.
- **`/docs` loads its scripts from a CDN** (FastAPI's default page) and therefore has FastAPI's
  default headers instead of the strict policy.

## Findings of the 2026-10-20 review

All found by probing the code with hostile input, fixed, and covered by tests:

| Finding | Effect before the fix | Fix |
|---|---|---|
| A UTF-16 JUnit file passed the byte search for `<!DOCTYPE` | its entities were expanded (verified: a 10-character entity became 100 characters) | DTDs found by expat in any encoding |
| Deeply nested XML suites, JSON arrays or TOML arrays | `RecursionError`: exit code 4, as if `qi` had a bug | input error (exit 3) naming the file |
| Fields of an unexpected type in mochawesome or Allure files (a string where an object belongs) | Python errors: exit code 4 | input error (exit 3) naming the file |
| A UTF-16-BE XML file | uncaught `ValueError`: exit code 4 | input error (exit 3) |
| Catalog and gate files had no size limit | a wrong path (a log, a database) would be read into memory whole | 10 MB / 1 MB limits |
| `--host 0.0.0.0` served the dashboard to the network without any login | every imported test name and failure message readable by anyone on the network | refused without a password; basic authentication with one |
| Markdown summaries escaped only `\|` | a test named `[click](https://...)` became a link on the CI job page | all Markdown punctuation escaped |
| Failure messages were stored as written | a token in an assertion message would reach history, reports and the dashboard | redaction of secret-shaped values |

Reporting a vulnerability: see [SECURITY.md](../SECURITY.md).

## Findings of the 2026-10-21 review (hosted operation, M5)

| Finding | Effect before the fix | Fix |
|---|---|---|
| No limit on wrong logins | unlimited password guessing at network speed | lock-out per address (429) |
| No way to serve public data without a login, except weakening the check | a public demonstration would need a shared password published with it, or a code change | explicit public mode, refused unless spelled `true` |
| Client address and scheme behind a proxy were the proxy's | a lock-out would have locked out everyone at once; no HSTS behind TLS | trusted proxies only, by setting |
| API answers had no cache rules | a shared cache could keep and serve an answer meant for a logged-in user | `private, no-store` with a login |
| No retention or verified backup | history grows forever; a damaged copy would be noticed only when needed | prune, backup with verification, check, restore |
| `Cross-Origin-Opener-Policy: same-origin` (added in this review) | Firefox (Playwright, Linux CI) lost page loads in 3 of 4 runs: a COOP navigation swaps processes | removed; the page opens no windows and cannot be framed (`frame-ancestors 'none'`), so it protected nothing here |
| First lock-out duration computed from the oldest failure (found by its own test) | with more failures than the limit, the lock-out lifted too early | computed from the failure that brings the count below the limit |
