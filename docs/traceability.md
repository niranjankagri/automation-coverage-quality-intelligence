# Requirement traceability

Traceability answers: *which requirements are tested, how, and did those tests pass?* It joins
three things:

```
catalog.toml                         result files (JUnit XML)
  requirements ──links── test cases ──automated_by──> results
       │                     │                          │
       └── coverage ─────────┘                          └── execution status (snapshot)
```

Metric formulas, filters and status rules: [metrics.md](metrics.md).

## The catalog file

TOML, two kinds of entries. A full example with 42 requirements and 44 test cases is
[samples/catalog.toml](../samples/catalog.toml), which takes its requirements from a generated
file: `include = ["requirements.toml"]` adds the entries of other files (paths inside the catalog's
folder, no nesting). Requirements can be kept by hand in the catalog or imported from a CSV export
([requirements-import.md](requirements-import.md)); test cases and their links stay hand-written.

```toml
[[requirement]]
id = "SHOP-006"                       # unique; letters, digits, . _ -
title = "Customers can check out and place an order"
description = "Logged-in customers can order ..."   # optional, up to 4,000 characters
feature = "Toolshop / Checkout"       # optional, grouping in reports
criticality = "critical"              # critical | high | medium | low (optional)
priority = "p1"                       # p1..p4 (optional)
risk = "high"                         # high | medium | low (optional)
platforms = ["web"]                   # optional, free text

[[test_case]]
id = "TC-SHOP-CHECKOUT"
title = "Guest and customer checkout"
automation_status = "automated"       # automated | manual | planned | blocked
test_type = "ui"                      # ui | api | mobile | database | integration | performance
framework = "playwright"              # optional, used by the framework filter
requirements = ["SHOP-006"]           # links; may be empty (reported as a gap)
automated_by = ["ui/checkout.spec.ts::*"]   # only for automated cases
```

Rules enforced when the file is loaded (each error names the entry and field):

- unknown fields and unknown values are errors (a typo must not silently drop data);
- duplicate requirement or test case ids are errors;
- a link to an unknown requirement is an error;
- `automated_by` on a manual, planned or blocked case is an error;
- the same requirement listed twice on a case is counted once, with a warning;
- an automated case without `automated_by` is allowed, with a warning (its results cannot be
  found).

## Writing `automated_by` patterns

A pattern is matched against the result **key** `classname::name`. Run `qi inspect` on a result
file to see the keys. Only `*` (any text) and `?` (one character) are wildcards; `[` and `]` are
literal, because real test names contain them:

| Framework | Example key | Pattern |
|---|---|---|
| pytest | `tests.api.test_notes::test_create_note_in_each_category[Home]` | `tests.api.test_notes::test_create_note_*` |
| Robot Framework | `Robot Framework Automation.Ui.01 Login::Standard User Can Log In` | `Robot Framework Automation.Ui.01 Login::*` |
| TestNG (Surefire) | `com.example.tests.api.OrderApiTest::cancellingGivesTheStockBack` | `com.example.tests.api.OrderApiTest::*` |
| Playwright Test | `ui/checkout.spec.ts::Checkout as a guest › guest is asked to sign in at checkout` | `ui/checkout.spec.ts::*` |

Alternatively a test can name its case: a JUnit property `test_id` on the testcase, or `[TC-1]`
in the test name. An explicit id that exists in the catalog wins over patterns.

`tests/integration/test_sample_traceability.py` checks that every pattern in the sample catalog
matches at least one real test: a pattern that matches nothing is almost always a typo or a
renamed test, and it would make a covered requirement look untested.

## What the report shows

```bash
qi coverage --catalog samples/catalog.toml                    # catalog only
qi coverage --catalog samples/catalog.toml samples/results    # + execution status
qi coverage --catalog samples/catalog.toml samples/results --criticality critical --framework playwright
```

| Section | Content |
|---|---|
| COVERAGE | requirement coverage, automation coverage, automated requirement coverage |
| GAPS | requirements without tests, without automation, critical without automation, automated cases linked to nothing |
| BY FEATURE / CRITICALITY / TEST TYPE / PLATFORM | the three metrics per group |
| EXECUTION | snapshot runs, outcome counts, pass rate, requirement statuses, failing (critical) requirements, automated cases without results, results that match no case |

On the demonstration data the catalog gives **38/42** requirement coverage, **37/43**
automation coverage and **32/42** automated requirement coverage; the two critical requirements
without automation are `SHOP-008` (card payment, planned) and `ADMIN-012` (second factor, no
test). These numbers are checked by hand and by a second, standard-library-only implementation
in the integration tests.

## Prioritised gaps

`qualityintel/traceability/gaps.py`, the Overview's **Coverage gaps by owner** and `GET /api/gaps`
(M13). A gap is an in-scope requirement with no linked test case (*no tests*) or with linked
cases none of which is automated (*not automated*). The order uses catalog fields only:

1. criticality: critical, high, medium, low, then unspecified;
2. risk: high, medium, low, then unspecified;
3. *no tests* before *not automated* (nothing at all is worse than a manual or planned test);
4. requirement id.

Gaps are grouped by `owner` (`unassigned` when the catalog names none); owners are listed by their
most urgent gap. Each gap names its linked cases' automation status (`manual`, `planned`,
`blocked`) and links the requirement. Nothing is guessed: a requirement without criticality is
*unspecified* and ranks after low.

On the sample catalog: 10 gaps (4 without tests, 6 not automated). The two critical ones rank
first: `ADMIN-012` (Admin team, no tests) and `SHOP-008` (Toolshop team, automation planned), the
same two that make the sample release gate fail.

## Known limits

- Matching is by name. A renamed test stops matching its pattern; the report then shows the
  case as "automated test case without results" and the renamed test as an unmatched result.
- A result that several cases claim counts for each of them; reports do not split it.
- Status uses only the snapshot (latest execution per suite, [metrics.md](metrics.md#terms)). Flakiness and trends need history
  (Milestone 6).
