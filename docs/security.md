# Security and reliability

What the platform assumes, what it protects against, how each protection is checked, and what is
left to the people who run it. Reviewed on 2026-10-20 (Phase 7 of the post-1.0 plan); the
findings of that review and their fixes are listed at the end.

## Assumptions

- **Inputs are untrusted.** Result files, Allure folders, mochawesome reports, catalogs, CSV
  exports and gate files may come from any CI job, fork or person. They may be broken, huge or
  hostile.
- **The person running `qi` is trusted.** Command line options, environment variables and file
  paths are theirs; `qi` reads and writes only the paths they give.
- **The dashboard is read-only and holds everything that was imported.** Anyone who can open it
  can read every requirement, test name and failure message in it.
- **No network access is needed.** `qi` sends nothing anywhere; the dashboard loads nothing from
  other origins (only `/docs`, FastAPI's API documentation page, loads its scripts from a CDN).

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
| Unauthenticated access to the dashboard | listens on 127.0.0.1 by default; any other address is **refused** unless `QI_DASHBOARD_PASSWORD` is set, which turns on HTTP basic authentication for every path (constant-time comparison) | `test_cli_dashboard.py`, `test_api.py`, browser test with a login |
| Secrets in stored data and reports | test logs (`system-out`, `system-err`), attachments and environment dumps are never read; Allure `environment.properties` and JUnit properties are read through an allow-list; failure messages pass through a redaction of secret-shaped values (authorization headers, bearer tokens, `password=`/`token:`/`api_key` assignments, credentials in URLs, JWTs, AWS and GitHub keys, private keys) | `tests/unit/models/test_redaction.py`, sample hygiene tests |
| Secrets in the tool's own output | the dashboard password is never printed (`qi config` shows only whether it is set; it is left out of the settings' repr); uvicorn's access log is off | `test_config.py`, `test_cli_dashboard.py` |
| Hostile CI artifacts (collection) | zip members checked before writing: no absolute paths, `..`, drive letters or links; at most 5,000 files and 200 MB unpacked (declared and actual), downloads at most 150 MB; only the configured path is unpacked; the token goes only to `api.github.com`, never to the storage redirect, never into messages | `tests/unit/collect/test_archive.py`, `test_github.py` ([collection.md](collection.md#security)) |
| Path tricks in catalogs | `include` takes plain relative file names only (no `..`, no nesting) | catalog unit tests |
| Vulnerable dependencies | exact versions pinned; CI job *Dependency audit* runs `pip-audit` on every installed version on every push (none known on 2026-10-20) | `.github/workflows/ci.yml` |
| A gate passing on incomplete input | missing, unreadable or empty results and incomplete pipeline executions make the gate *incomplete* (exit 3) | gate and pipeline tests ([quality-gates.md](quality-gates.md), [pipelines.md](pipelines.md)) |

## Running the dashboard for a team

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
- **No rate limiting or brute-force protection** on the dashboard login; rely on the proxy for
  that when the dashboard is reachable from a wide network.
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
