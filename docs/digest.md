# Daily quality digest

What one day added to the history, in five short sections, each line linked to the dashboard page
that shows its evidence (M13). Built only from analyses the dashboard already shows, applied to the
runs started **on or before** the digest day, so a digest of an earlier day never changes when later
runs arrive.

```bash
qi digest --catalog samples/catalog.toml samples/results --gate samples/gates/release.toml --day 2026-10-13
qi digest --catalog catalog.toml --database .qi/quality.db --markdown --base-url https://qi.example
```

`GET /api/digest?day=YYYY-MM-DD` returns the sections as data; `GET /api/digest/summary` returns the
same digest as copyable text and Markdown with links relative to the dashboard. The page filters
(repository, framework, dates ...) apply to both.

## The day and the previous day

| | Definition |
|---|---|
| Digest day | `--day` / `day=`, else the **newest UTC date on which a run started** in the scope (the history's newest day, not today's date) |
| Previous day | the previous date **with runs**, not the calendar day before (a weekend without runs is skipped) |
| No runs that day | no sections, a note "no dated run in this scope on ..."; `qi digest` exits 3 |

## Sections

| Section | Content | Link |
|---|---|---|
| Runs | runs that started on the day, their results and failed + error results, in total and per repository ("repository not recorded" for hand-imported files) | Runs page for that day |
| Release gate (only with a gate) | the gate's verdict on the day's end-of-day snapshot and on the previous day's; when it changed, the rules that started and stopped failing ([quality-gates.md](quality-gates.md#gate-history)) | Trends; the day's runs |
| Regressions | suites whose newest build started that day and fails tests its previous build on the same branch passed ([history.md](history.md#latest-regressions)) | Compare page for the two builds |
| Tests that changed | per repository, test keys failing in the end-of-day snapshot that did not fail in the previous day's, and the reverse; the first 5 started-failing tests by name | Trends of the repository; each test's history |
| Recurring failures seen again | recurring failure causes ([metrics.md](metrics.md#recurring-failures)) whose latest occurrence is on the day, in rank order, at most 5 | the newest run with that cause |

A section with nothing to report says so in one line (for example "no test started or stopped failing
since 2026-10-12") instead of disappearing, so an empty section is visibly checked, not forgotten.

## On the sample data

- **13 Oct**: 4 runs, 197 results, 1 failed. *Tests that changed* names
  `CustomerManagementTest::adminEditsACustomer`, the real Firefox login timeout of that nightly.
- **17 Oct** (with the release gate): still failed, reasons changed; *executed tests* and
  *automated test cases without results* stopped failing.
- **19 Oct**: 7 runs with 3 failed results, yet no test changed: they are Playwright attempts 1 and 2,
  and attempt 3 passed, so the end-of-day snapshot holds no failure.

## Limits

- Deterministic text only; no AI-written summary (M13 item 10 is deferred until a model is available
  and these numbers are the reference to check it against).
- Hand-imported files have no repository, so per-repository lines group them as "repository not
  recorded".
- The catalog is today's, as in the gate history.

Checked by `tests/unit/test_digest.py`, `tests/unit/test_cli_digest.py` and the digest tests in
`tests/unit/dashboard/test_api.py` (the 13 Oct sample day).
