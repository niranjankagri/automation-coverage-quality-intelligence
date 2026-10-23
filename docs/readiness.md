# Release readiness

The overview starts with one status for the scope chosen on the page: **Ready**, **At risk**,
**Blocked** or **Unknown**. It is computed in `qualityintel/readiness.py`, never in the browser,
from the release gate the dashboard is started with:

```bash
qi dashboard --catalog samples/catalog.toml --database .qi/quality.db --gate samples/gates/release.toml
```

## Policy

Checked in this order; the first that applies is the status. Every reason is listed under it.

| Status | When | Why |
|---|---|---|
| **Unknown** | no gate is configured; or the gate is *incomplete*: results missing, unreadable or empty, a pipeline incomplete | missing evidence is never shown as ready |
| **Blocked** | the gate decided and at least one rule failed | each failing rule is listed with actual and expected value |
| **At risk** | the gate passed, but: flaky candidates in the scope, incomplete pipeline collections in the last 7 days, or the dashboard could not refresh its data (stale) | these are real risks the gate's rules do not measure |
| **Ready** | the gate passed and none of the above applies | |

A high pass rate alone never makes a scope ready. The gate's rules are applied to the scope
chosen on the page (repository, feature, framework ...), the same way `qi gate` applies them to
the files it is given ([quality-gates.md](quality-gates.md)).

## The numbers next to it

| Number | Meaning |
|---|---|
| Test executions | results in the snapshot of the scope: the latest execution of every suite, all files of a job's latest attempt ([metrics.md](metrics.md#terms)) |
| Critical without automation | critical requirements in scope without an automated test case |
| Flaky candidates | tests the history analysis classifies as flaky candidates, with evidence on the Stability page ([history.md](history.md)) |
| Incomplete pipelines (7 days) | collection records of the last 7 days that are incomplete, for the chosen repositories ([collection.md](collection.md)) |
| Latest collection | when results were last collected from CI |

Requirement coverage, automated requirement coverage and the execution pass rate are the cards
below the status, each with numerator and denominator ([metrics.md](metrics.md)).

`GET /api/readiness` returns the status, the reasons, the gate's rules, the scorecard and these
numbers for the scope in the query.

## Scorecard

The **Scorecard** under the status (M13) lists every criterion the status was derived from, in
the order the policy checks them, so the status can be checked by hand:

| Row | Source | Result | Effect on the status |
|---|---|---|---|
| release gate configured | gate | `pass`, or `unknown` without a gate | `unknown` without a gate |
| gate inputs complete | gate | `pass`, or `unknown` with the gate's input problems | `unknown` when the gate cannot decide |
| each gate rule | gate | `pass`, `fail` or `not applicable` (passing per config), with measured value and threshold | `blocks` when it fails and the gate could decide; `unknown` when it fails on incomplete inputs |
| flaky candidates | policy | `warning` above 0 | `at risk` |
| incomplete pipeline collections (7 days) | policy | `warning` above 0 | `at risk` |
| data freshness | policy | `warning` when stale | `at risk` |

Every other row has `none`. Reading the rows gives the status: any `unknown` row makes it
Unknown, otherwise any `blocks` row Blocked, otherwise any `at risk` row At risk, otherwise Ready.
Each row links its evidence page (`CRITERION_EVIDENCE` in `workspace.py`: failing requirements,
failed tests, critical gaps, the Stability page, incomplete pipelines, Collection); a test enables
every gate rule and fails if one has no evidence page.

## Checked by

`tests/unit/test_readiness.py` (every branch of the policy), `tests/unit/dashboard/test_api.py`
(on the real samples: no gate = unknown, the release gate blocks on SHOP-008 and ADMIN-012, the
nightly gate passes but its 4 flaky candidates make it at risk; the scorecard rows and their
evidence pages), and a browser test of the panel.
