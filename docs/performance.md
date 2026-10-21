# Performance

What the dashboard costs on production-sized data, how that was measured, and the guards that
keep it that way. All numbers come from real runs on the dates given; they compare only on the
same machine.

## The data

The hosted history on 2026-10-21: 222 runs and 23,176 results from 23 repositories (it has grown
since; the live site reported 250 runs and 29,898 results the same day). The tests use a
deterministic stand-in of the same size: the 43 real sample runs copied 12 times with later dates
and new builds (516 runs, 28,140 results, 221 distinct tests).

## Before and after (2026-10-21)

`python tools/benchmark.py DATABASE` on the same file for each version (the hosted history
before the fixes), laptop with 12 CPUs, Python 3.13.14, Windows 11, median of 3 rounds. *Uncached*
is the first request of a view on a new snapshot; *cached* the next one.

| View | before (24f6475) | matching once per test (1bf93b9) | now, uncached | now, cached |
|---|---|---|---|---|
| Overview (summary + readiness) | 2.146 s | 0.327 s | 0.365 s | 0.006 s |
| Tests | 1.493 s | 0.113 s | 0.104 s | < 0.001 s |
| Stability | 1.620 s | 0.304 s | 0.293 s | < 0.001 s |
| Requirements (list + matrix) | 0.344 s | 0.030 s | 0.016 s | 0.001 s |
| Trends | 0.355 s | 0.049 s | 0.055 s | < 0.001 s |
| Pipelines | 0.017 s | 0.017 s | 0.018 s | 0.017 s (not cached) |
| Build snapshot from the database | 0.42 s | 0.39 s | 0.36 s | |
| Warm-up before going live | – | – | 0.42 s | |
| Peak memory, build + warm (`tracemalloc`) | 30.8 MB | 30.8 MB | 41.5 MB | |

On the live site (Render free plan, Frankfurt, measured from India, so about 0.25 s of each
figure is the network): readiness 9.4 s → 0.3 s, stability 14 s → 0.45 s, tests 7.2 s → 0.7 s;
the overview page took over 30 s before 1bf93b9, 6.5-7 s after it, and 1.4 s now.

**What changed.** (1) Every result was matched against every `automated_by` pattern on every
request (1.46 million regular-expression matches for one view); a test's matches now depend on
its key only and are computed once (1bf93b9). (2) A snapshot never changes, so its
time-independent analyses (traceability report, stability, tests, trends) are kept per snapshot,
at most 64 filter combinations; readiness is computed each time because its 7-day window follows
the clock. (3) The default views are computed before a snapshot goes live, at start and after
every refresh, while the previous snapshot still answers. The memory price is about 11 MB.

## Guards in CI

`tests/performance/test_budgets.py` (marker `performance`, part of every test job):

- **Structural:** pattern matches for 12 times the runs equal those for one copy: the work grows
  with distinct tests, never with runs. Independent of machine speed; it fails if the N x M
  loop returns.
- **Budgets** on the 28,140-result stand-in, about four to five times the laptop figures (overview
  0.26 s, tests 0.12 s, stability 0.24 s, trends 0.57 s, warm-up 0.37 s; best of three): overview
  1.2 s, tests 0.6 s, stability 1.0 s, trends 2.5 s, warm-up 4 s, any view after the warm-up 0.05 s.
  The code from before the fixes takes about 2.6 s for the overview at this size and fails.
- **Freshness:** a refresh produces a new snapshot with its own cache; views on it show the new
  data (`tests/unit/test_live.py::test_cached_views_never_outlive_their_data`).

## Search and Needs Attention (M12, 2026-10-21)

Same stand-in and machine: search index 0.063 s (0.07 s for the 2,095 entries of the hosted
history), a query about 0.2 ms; Needs Attention 0.35 s uncached, under 1 ms cached; both
computed by the warm-up; the extra memory about 0.2 MB. Budgets: index 0.5 s, query 0.05 s,
Needs Attention 2 s uncached.

## Not needed (yet)

- **SQLite stays.** Building the snapshot from the database takes 0.36 s for 23,000 results; the
  time went into analysis, not storage. Reconsider only with many concurrent writers or a history
  much larger than memory.
- **No API paging.** The largest answer (`/api/tests`, 1,911 rows) is built in about 0.1 s and
  rendered 50 rows per page; the browser filters and sorts the rows it already has.
- **Pipelines** are not cached: 0.017 s.
