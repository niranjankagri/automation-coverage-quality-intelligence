# Quality gates

A quality gate turns the numbers into a decision a pipeline can act on:

```bash
qi gate --catalog samples/catalog.toml --config samples/gates/release.toml samples/results \
        --json reports/gate.json --html reports/gate.html --summary "$GITHUB_STEP_SUMMARY"
```

## Exit codes

| Code | Gate status | Meaning | Pipeline should |
|---|---|---|---|
| 0 | passed | every configured rule passed | continue |
| 1 | failed | at least one configured rule failed | stop the release; the report names what failed |
| 2 | - | wrong usage or invalid gate file (unknown key, value out of range, no rule at all) | fix the pipeline definition |
| 3 | incomplete | input missing or invalid: a result path matched nothing, a file is unreadable or not JUnit XML, the result files contain no tests, or the catalog cannot be read | fix the test step; **never** treated as passed |
| 4 | - | internal error in `qi` (a crash) | report a bug; a crash never looks like a gate decision |

**Missing or broken input can never produce a pass.** When execution rules are configured and no
result was read, the gate is `incomplete` (exit 3) even if every coverage rule passes. One broken
file among good ones also makes it incomplete. The catalog being unreadable still writes the
JSON/HTML/Markdown reports, so the CI page shows why no decision was made.

## Gate file

TOML; every rule is optional and only configured rules are evaluated. Unknown keys are errors (a
misspelt threshold must not silently switch a rule off), and a file that configures no rule is
refused (a gate that checks nothing would always pass).

```toml
name = "release gate"
not_applicable = "fail"       # what a rule does when its metric is n/a: "fail" (default) or "pass"

[coverage]
min_requirement_coverage = 90            # percent
min_automation_coverage = 80             # percent
min_automated_requirement_coverage = 75  # percent
max_uncovered_critical = 0               # critical requirements without an automated test case
max_requirements_without_tests = 5

[execution]
min_pass_rate = 98                       # percent, latest run per context, skips not counted
max_failing_critical = 0                 # critical requirements with a failing automated test
max_failing_requirements = 2
max_failed_tests = 0                     # failed or errored tests in the latest runs
min_results = 200                        # tests with a verdict: catches a suite that silently ran fewer
max_automated_cases_without_results = 0  # automated cases whose tests vanished or were renamed

[scope]                                  # optional, same filters as `qi coverage`
criticality = ["critical", "high"]
browser = ["firefox"]
```

Metric definitions are in [metrics.md](metrics.md). Thresholds compare the **unrounded** value:
66.66 % does not pass a 66.7 % threshold even though it is displayed as 66.7 %.

## Reports

All formats are built from one document, so they cannot disagree.

| Format | Option | For |
|---|---|---|
| Text | always, on stdout | CI log: verdict, one line per rule, failing items |
| JSON | `--json FILE` | machines; `schema_version` 1; keys: `gate` (name, status, exit_code, scope), `input_problems`, `rules` (name, status, fails_gate, actual, expected, explanation, items), `metrics`, `gaps`, `failing_requirements`, `failing_critical`, `inputs` |
| HTML | `--html FILE` | people; one self-contained file (no script, no external resource), every value escaped |
| Markdown | `--summary FILE` (appended) | the run page: `--summary "$GITHUB_STEP_SUMMARY"` |

![Release gate HTML report on the sample data](images/gate-report-release.png)

## The sample gates

| Gate | Input | Result | Why |
|---|---|---|---|
| [`samples/gates/release.toml`](../samples/gates/release.toml) | all sample results | **failed (1)** | `SHOP-008` (card payment, only planned) and `ADMIN-012` (second factor, no test) are critical and have no automated test |
| [`samples/gates/nightly.toml`](../samples/gates/nightly.toml) | all sample results (latest run per context) | **passed (0)** | 221 of 221 tests passed |
| `nightly.toml` | Playwright run 39229363499, attempt 1 (19 Oct) | **failed (1)** | the checkout test failed, so critical requirement `SHOP-006` is failing |
| `nightly.toml` | a path that does not exist | **incomplete (3)** | no test results were read |

The CI job `quality-gate` runs all four on every push and asserts each exit code, so a change that
made a broken input pass, or a real gap disappear, would fail the build. Its reports are kept as the
`quality-gate-reports` artifact and summarised on the run page.

## Using it in another pipeline

GitHub Actions, after the test step (which may itself fail):

```yaml
- name: Tests
  run: pytest --junitxml=reports/junit.xml
  continue-on-error: true            # the gate decides, with all the context
- name: Quality gate
  if: always()                       # also when the tests failed or crashed
  run: >-
    qi gate --catalog quality/catalog.toml --config quality/release.toml reports/
    --context framework=pytest --context build=${{ github.sha }}
    --json reports/gate.json --html reports/gate.html --summary "$GITHUB_STEP_SUMMARY"
```

`if: always()` matters: if the test step crashed and wrote nothing, the gate still runs and ends
with exit code 3 instead of being skipped.
