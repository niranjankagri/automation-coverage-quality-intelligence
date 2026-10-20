# Metric definitions

Every number this platform reports is defined here: what is counted, from which data, and
what happens at the edges. Code that computes a metric links back to this page, and each
formula has unit tests with hand-calculated expectations.

General rules:

- Every metric is a **ratio that keeps its counts**: reports show `85.0 % (17/20)`, never a bare
  percentage, so a reader can check the arithmetic.
- **Zero denominator = not applicable (`n/a`)**, never 0 % and never 100 %. A gate that meets an
  `n/a` metric fails unless it is explicitly configured to allow it (Milestone 7).
- Percentages are rounded to one decimal for display only; gates compare the unrounded value.
- **No combined score.** The metrics answer different questions ([ADR 0004](adr/0004-separate-metrics.md)).

## Terms

| Term | Meaning |
|---|---|
| Requirement | An entry in the catalog's requirement list. |
| Test case | An entry in the catalog's test case list, with an automation status: `automated`, `manual`, `planned` or `blocked`. |
| Link | A requirement id listed in a test case's `requirements`. The same link listed twice counts once (with a warning). |
| Result | One `<testcase>` element of an imported result file. Its **key** is `classname::name` (or `name` when there is no classname). |
| Matched result | A result that belongs to a test case: its explicit test id equals the case id, or its key matches one of the case's `automated_by` patterns. |
| Verdict | A result whose outcome is `passed`, `failed` or `error`. `skipped` is not a verdict. |

## 1. Requirement coverage

> Share of requirements that have at least one linked test case, of any automation status.

```
requirement coverage = requirements with >= 1 linked test case
                       ---------------------------------------
                       requirements in scope
```

"In scope" = all requirements, or those that match the active filter (feature, criticality,
platform). A requirement linked only to a `planned` or `blocked` test case **counts as covered
here**: someone designed a test. Whether it runs automatically is metric 2 and 3.

## 2. Automation coverage (test cases)

> Share of linked test cases that are automated.

```
automation coverage = linked test cases with status "automated"
                      -------------------------------------------
                      test cases linked to >= 1 requirement in scope
```

Denominator: only test cases linked to an in-scope requirement. Unlinked test cases are left out
on purpose (they are reported as a gap instead), so adding unrelated automated tests cannot raise
this number. A test case linked to several requirements counts once.

## 3. Automated requirement coverage

> Share of requirements that have at least one automated linked test case.

```
automated requirement coverage = requirements with >= 1 linked "automated" test case
                                 ---------------------------------------------------
                                 requirements in scope
```

This answers "if nobody tests by hand, which requirements are still checked?". It is always less
than or equal to requirement coverage.

## 4. Execution pass rate

> Share of verdicts that passed, for one run or a set of runs.

```
execution pass rate = results with outcome "passed"
                      ------------------------------------------------
                      results with outcome "passed", "failed" or "error"
```

Skipped results are **left out of the denominator** and reported as their own count: a skip says
nothing about the product. Counted as "not passed" it would make a run with many skips look
broken; counted as "passed" it would make it look healthy. A run where every test was skipped has
pass rate `n/a`.

Execution pass rate is about the automated tests that ran, not about requirements: a 100 % pass
rate with 40 % requirement coverage means "what we test works", not "the product works".

## Coverage gaps (reported as lists, not ratios)

| Gap | Definition |
|---|---|
| Requirement without tests | In-scope requirement with no linked test case. |
| Requirement without automation | Has linked test cases, none of them `automated`. |
| Unlinked automated test case | `automated` test case linked to no requirement. |
| Unmatched result | Result that matches no test case in the catalog (the framework runs a test nobody mapped). |
| Automated test case without results | `automated` test case with no matched result in the analysed runs (maybe deleted, renamed or not run). |
| Uncovered critical requirement | Requirement with criticality `critical` and no linked `automated` test case. |

## Breakdowns

Coverage metrics are also computed per **feature**, **criticality**, **platform** and
**test type**. Missing metadata is grouped as `unspecified`, never guessed (and `unspecified`
can be used as a filter value to find incomplete records).

- Feature, criticality, platform group the **requirements**. A requirement with two platforms
  is in both platform rows.
- Test type groups the **test cases**: the row for `api` keeps every in-scope requirement in the
  denominator and counts only the linked `api` test cases. "api: requirement coverage 38 %"
  therefore reads "API tests reach 38 % of the requirements".

Rows can add up to more than the total; the total is always computed directly, never summed.

## Filters

| Filter | Applies to | Effect |
|---|---|---|
| feature, criticality, platform | requirements | chooses the requirements in scope (the denominators) |
| test type, framework | test cases | only these linked cases count; a requirement whose cases are all filtered out has "no tests" in this scope |
| framework, environment, browser | runs | chooses the runs for the execution status |

## Execution status

Execution status joins the catalog with result files.

**Snapshot.** For each *run context* (framework, environment, browser, platform; the build is
not part of it) only the **latest** run is used. A re-run attempt replaces the attempt before it;
an older nightly does not hide today's result. Runs without a timestamp sort before dated runs.

**Matching.** A result belongs to a test case when it carries the case id explicitly (JUnit
property `test_id`, or `[TC-1]` in its name), otherwise when its key matches one of the case's
`automated_by` patterns (`*` and `?` only). One result may belong to several cases.

**Test case status** (automated cases, from their snapshot results):

| Status | Rule |
|---|---|
| failing | at least one result `failed` or `error` |
| passing | at least one `passed`, none failed |
| skipped | every result `skipped` |
| not run | no result at all |

Manual, planned and blocked cases are `not automated`.

**Requirement status** = the worst status of its automated cases, in the order
`failing` > `not run` > `skipped` > `passing`; `not automated` when it has no automated case.
`not run` ranks above `passing` on purpose: if one automated case did not run, the requirement
is not fully verified even though another case passed.

**Failing critical requirement** = criticality `critical` and status `failing`.

The execution pass rate (section 4) is computed over **all** snapshot results, matched or not:
it describes what ran.

## History metrics

Computed by `qualityintel.history.analysis` over stored or freshly imported runs.

**Comparable executions.** A test is only compared with itself (same key) in the same **run
context** (framework, environment, browser, platform). A Firefox failure says nothing about
Chrome.

**Verdicts and window.** A verdict is an execution that passed, failed or errored; skips are
ignored. Classification looks at the last `window` verdicts (default **10**) of a test in one
context.

**Flip.** Two consecutive verdicts where one passed and the other did not.

### Stability classes (first matching rule wins)

| # | Class | Rule (defaults) | Meaning |
|---|---|---|---|
| 1 | insufficient data | fewer than **3** verdicts and no pass-after-retry | too early to say anything |
| 2 | consistently failing | the last **2** verdicts both failed or errored | a reproduced failure: treat as a real defect, **not** as flakiness |
| 3 | flaky candidate | a pass after a retry inside one run, **or** one build that both passed and failed, **or** at least **2** flips (`flips_for_flaky`) | mixed results without a code change; a *candidate*, to be confirmed by a person |
| 4 | new failure | the latest verdict failed (and none of the above) | broke recently; one failure is not yet a confirmed failure |
| 5 | recovered | a failure earlier in the window, passing now | watch it |
| 6 | stable | every verdict passed | |

Failure rate (shown with every class) = failed or errored verdicts / verdicts in the window.

"Same build passed and failed" is the strongest flaky signal the data can give: nothing in the
code changed between the two outcomes. On the sample data it finds four tests: one Selenium test
that timed out once on 13 Oct (build `f5a40d5` passed on the other nightlies) and three Playwright
tests that failed in attempts 1 or 2 of run 39229363499 and passed on attempt 3 of the same commit.

### Recurring failures

Failure **signature** = exception type + first line of the message, with UUIDs, hex ids and all
numbers masked (`Timeout 15000ms` and `Timeout 30000ms` are one cause). A signature is
*recurring* when it occurs in at least **2** different runs. Tests with outcome `error` in at
least 2 runs are listed separately (errors usually mean set-up or environment problems, not
assertion failures).

### Durations

| Metric | Rule (defaults) |
|---|---|
| Slow tests | highest **median** duration per test and context (one slow run does not make a test slow) |
| Duration regression | the last **2** durations (`slow_confirm_runs`) are each more than **50 %** above **and** at least **1.0 s** above the baseline; baseline = median of up to `window` earlier durations, at least **3** |

The absolute floor stops 0.01 s -> 0.02 s from counting as "100 % slower". Requiring two slow
runs in a row is a lesson from the sample data: in the 19 Oct nightly individual TestNG tests
reported up to 5x their usual time while the suite's wall time did not change (tests running in
parallel share the machine). With one run, 19 tests were flagged; with two consecutive runs, two
remain, both slow on the first two runs of a new build.

### Run comparison and grouping

`compare(base, head)` lists newly failing, fixed, still failing, added, removed and clearly
slower tests (same thresholds as duration regressions). Runs can also be grouped by build,
environment or framework with a pooled pass rate (all results of the group together).

### Limits of these numbers

- **Small samples.** With 5 runs, one failure is a 20 % failure rate. Classes need at least 3
  verdicts, but a stable class after 3 runs is weak evidence.
- **Identity is the test name.** Renaming a test starts a new history; the old one stays.
- **Context is only as good as the files.** Runs whose files do not record browser or environment
  (and that were imported without `--context`) share one context and are compared with each other.
- **Retries are only visible if the producer reports them.** Surefire writes `flakyFailure`;
  pytest, Robot and Playwright's JUnit output do not record in-run retries. A CI re-run is
  visible only if each attempt's file is imported (as the Playwright samples are).
- **Time order** uses the suite timestamp. Files without one sort before dated runs.
- **Durations in parallel suites** depend on what ran beside the test; trust trends, not
  single values.
- **Flaky candidate is a hypothesis.** The class says the history *looks* intermittent. The cause
  (test, product, environment, test data) needs a person; the sample candidates were all caused
  by the environment (public demo site outage, a page-ready timeout on Firefox).
