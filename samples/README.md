# Sample data

## `results/`: real CI result files

Every file here is a JUnit XML report that a GitHub Actions run of one of my public test
automation repositories produced. Nothing in them is invented; they were cleaned with
[`tools/sanitize_junit.py`](../tools/sanitize_junit.py) before committing.

| Folder | Producer | Repository / CI job | Runs |
|---|---|---|---|
| `pytest-notes-api` | pytest 9 (`--junitxml`) | [python-pytest-framework](https://github.com/niranjankagri/python-pytest-framework), API job | 7 (13-19 Oct 2026) |
| `pytest-notes-ui-chromium` | pytest 9 + Playwright for Python | python-pytest-framework, UI job (Chromium) | 7 |
| `robot-saucedemo-chrome` | Robot Framework 7 (`--xunit`) | [robot-framework-automation](https://github.com/niranjankagri/robot-framework-automation), Chrome job | 11 (9-19 Oct) |
| `testng-enterprise-regression-firefox` | Maven Surefire 3.5 + TestNG 7 (Selenium) | [enterprise-test-automation-framework](https://github.com/niranjankagri/enterprise-test-automation-framework), nightly regression on Firefox | 13 (7-19 Oct) |
| `playwright-toolshop-firefox` | Playwright Test 1.64 (`merge-reports --reporter junit`) | [playwright-typescript-framework](https://github.com/niranjankagri/playwright-typescript-framework), Firefox job | 5 attempts of 3 runs |

**File names:** `<date>_<commit>_<GitHub run id>.xml`; Playwright files add `-attempt<N>`
because one run was re-run twice. The commit is the build that was tested.

**What happened in these runs (all real):**

- `testng-enterprise-regression-firefox/2026-10-13_...`: one failure, a Selenium
  `TimeoutException` in `CustomerManagementTest.adminEditsACustomer` (the login page did not
  become ready on Firefox within 10 s). The next nightly passed without a code change.
- `playwright-toolshop-firefox/2026-10-19_..._39229363499`: attempt 1 had one failed checkout
  test, attempt 2 had two errors (the public demo site timed out on API calls), attempt 3 passed.
  Same commit throughout: an outage of the site under test, not a code change.
- Everything else passed.

**What the sanitiser changed:**

- removed test logs (`<system-out>`, `<system-err>`), `hostname` attributes, XML comments and
  properties outside an allow-list (Surefire writes every JVM property: class paths, home
  directories, user names);
- added run context as suite properties: `framework`, `browser`, `environment=ci`,
  `platform=linux` and `build=<commit>`, taken from the CI job definition and run page;
- added a suite `timestamp` with the CI run's start time where the producer wrote none
  (Surefire), and replaced the merge time that `playwright merge-reports` writes with the
  start time of the run attempt.

Test names, outcomes, durations and failure messages are unchanged. `tests/integration/test_real_samples.py`
checks every file against the totals the producer itself wrote into it.

**Not included:** a Playwright Chromium set (artifacts were too slow to download completely in
the session that built these samples) and Cypress (its CI writes mochawesome JSON, not JUnit
XML; no adapter has been written for it, so Cypress support is not claimed).
