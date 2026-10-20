# Dashboard

A read-only web view over a requirement catalog and imported results. It shows the same numbers
as `qi coverage`: both read the core packages, and the dashboard calculates nothing itself
([architecture rule](architecture.md#layers-and-the-dependency-rule)).

```bash
qi dashboard --catalog samples/catalog.toml samples/results
# qi: dashboard on http://127.0.0.1:8000  (42 requirements, 43 runs)
```

`--host` / `--port` (or `QI_DASHBOARD_HOST` / `QI_DASHBOARD_PORT`) change the address. The data is
read once at start-up; restart to load new result files.

## Views

| View | Shows | Drill-down |
|---|---|---|
| Overview | requirements in scope; requirement coverage, automation coverage, automated requirement coverage; execution pass rate and pass / fail / error / skip counts of the snapshot; snapshot runs; critical requirements without automation; failing requirements; other gaps | every card opens the list behind it (e.g. requirement coverage -> requirements without tests) |
| Requirements | id, title, feature, criticality, automated / linked test cases, coverage status, execution status; status filter | requirement -> its test cases and their latest executions |
| Tests | every executed test with run, pass, fail, error, skip counts and last failure; search; latest-outcome filter | test -> full execution history, failure message and stack trace |
| Runs | every imported run with context, counts and pass rate | run -> all results, failures first |

Filters (feature, criticality, test type, framework, environment, browser) apply to every view
and are kept in the address, so a filtered view can be bookmarked or shared. The drop-down values
come from the data (`/api/facets`), never from a fixed list.

Coverage and pass rate are separate cards on purpose ([ADR 0004](adr/0004-separate-metrics.md)).

## Screenshots (sample data)

| | |
|---|---|
| ![Overview](images/dashboard-overview.png) | ![Requirements, critical only](images/dashboard-requirements.png) |
| ![History of the test that failed on 13 Oct](images/dashboard-test-history.png) | ![Runs, dark theme](images/dashboard-run.png) |

Made by `python tools/screenshots.py`; CI takes the same screenshots on every run (artifact
`dashboard-e2e`).

## JSON API

Interactive documentation: `/docs` (generated from the routes, so it cannot drift).

| Route | Answer |
|---|---|
| `GET /api/health` | status, version, number of requirements and runs |
| `GET /api/facets` | filter values present in the data |
| `GET /api/summary` | coverage metrics, gaps, snapshot runs, outcome counts, pass rate |
| `GET /api/requirements?status=` | requirement rows; `status` = a coverage or execution status |
| `GET /api/requirements/{id}` | one requirement, its test cases and their latest executions |
| `GET /api/tests?outcome=` | every executed test with counts |
| `GET /api/tests/history?key=` | all executions of one test, newest first (key in the query: it contains `/` and `::`) |
| `GET /api/runs` | runs, newest first |
| `GET /api/runs/{run_id}` | one run, failures first |

Filter parameters are repeatable: `?criticality=critical&criticality=high&browser=firefox`.
Unknown ids give **404**; a value that can never match (`criticality=urgent`, `outcome=green`)
gives **422** with the allowed values; a valid value nobody used (`browser=safari`) gives an empty
scope with `n/a` metrics.

## Front end

Plain HTML, CSS and JavaScript served by the package (no build step, no CDN). All text is
inserted with `textContent`, because real test names contain quotes, brackets and `<`. Pages are
served with a strict Content-Security-Policy (`default-src 'self'`, no inline script or style),
`X-Content-Type-Options: nosniff` and `Referrer-Policy: no-referrer`. Light and dark themes
follow the operating system.

States: a loading line while data is fetched; an empty-state text when a list has no rows; an
error box with the API's message and a Retry button when a request fails; a message for unknown
pages and ids.

## How it is tested

| Level | What | Where |
|---|---|---|
| View models | every number, order and filter of every view, without a server | `tests/unit/test_workspace.py` |
| API | routes, filters, 404 / 422, security headers, OpenAPI route list | `tests/unit/dashboard/test_api.py` (FastAPI TestClient) |
| Browser | overview numbers, drill-down, filters in the URL, detail pages, real failure in the history, empty state, API error + retry, unknown pages, phone and tablet width without sideways scrolling, skip link; any JavaScript console error fails the test | `tests/e2e/test_dashboard.py` (Playwright, Chromium), CI job `dashboard` |

Found by the browser tests while building it: the section links in the header dropped the active
filters (fixed: they are rebuilt with the filters on every view change), and a broken string in
the script (caught by the console-error check).
