# Needs attention

The **Needs attention** page (`#/attention`, `GET /api/attention`) gathers what the evidence
shows needs a look, in one list, for the scope chosen in the filter bar. It invents nothing: each
finding is built from records the other pages show, says why it is listed, how much evidence
supports it, when it was first and last seen, and links to those records (and to the GitHub run
where there is one). Code: `qualityintel/attention.py` (the rules) and `Workspace.attention`.

## States

| State | Meaning |
|---|---|
| **open** | the latest evidence still shows the problem |
| **suspected** | a flaky candidate: passed and failed in the same context; a suspicion from the pattern, never a proven cause |
| **unknown** | not enough evidence to say (e.g. a recurring failure whose tests have no later verdict) |
| **resolved** | later evidence shows it gone; kept as a historical observation |

Nothing is called *open* unless the latest evidence supports it.

## Action center groups

The dashboard groups the existing states to make the next action clear without changing the
finding rules:

| Dashboard group | Included states | Meaning |
|---|---|---|
| **Investigate now** | open | Latest evidence still supports the finding. |
| **Monitor** | suspected, unknown | The pattern is mixed or evidence is insufficient to resolve it. |
| **Resolved** | resolved | Later evidence shows the condition gone; history remains visible. |

These labels do not add a severity or infer a cause. Findings remain in the backend's documented
state and severity order. Finding-kind filtering happens in the API before its 200-finding response
limit. Each row keeps the observed reason, evidence count, first and last seen, repository when
recorded, and the investigation and GitHub links when available.

## Findings, by severity

The list is sorted by state (open, suspected, unknown, resolved), then by this documented
severity, then by the latest observation. Severity is an order of urgency, not a score.

| Severity | Kind | Listed when | State |
|---|---|---|---|
| 1 | newly failing | a test failed or errored in the latest execution of its suite and passed in the execution before (a suite: run context, repository and job; an execution: a pipeline job attempt with all its files) | open |
| 2 | incomplete pipeline | a collected pipeline attempt has missing jobs or reports (missing or expired artifacts, unreadable reports) | open, or resolved when a later run of the same workflow is complete |
| 3 | critical gap | a critical requirement in scope has no automated test case | open (from the catalog: on the hosted demonstration the catalog is synthetic, see its notice) |
| 4 | recurring failure | the same failure signature in two or more runs ([metrics.md](metrics.md), recurring failures) | open while one of its tests fails in its latest execution; resolved when all pass; else unknown |
| 5 | duration regression | a test confirmed slower over consecutive runs ([metrics.md](metrics.md), durations) | open |
| 6 | flaky candidate | the stability class *flaky candidate* | suspected |
| 7 | overdue collection | a repository's last collection is older than the expected hours (`QI_COLLECTION_HOURS`) | open |

Not *newly failing*: a test new in the latest execution (nothing to compare with), and a failure
a later re-run attempt passed (the re-run is the newer execution).

## Filters and limits

Repository and date filters apply to runs and collection records; requirement filters to the
critical gaps. At most 200 findings are listed (the total is shown). A `kind` query filters before
that limit and reports counts for the selected kind. Findings from runs are cached per data
snapshot; collection freshness is evaluated at each request.
