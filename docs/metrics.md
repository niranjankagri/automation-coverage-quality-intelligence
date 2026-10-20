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

Defined in Milestone 6 (comparable executions, flaky-test candidates, recurring failures,
duration regressions) and added to this page then.
