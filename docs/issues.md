# Issue drafts for recurring failures

The Stability page and `GET /api/issue-suggestions?limit=10` turn the highest-ranked recurring
failures ([metrics.md](metrics.md#recurring-failures)) into **issue drafts** (M13). The plan asks for
"GitHub issue suggestions for recurring failures, requiring approval before creation"; the
approval is built in by never creating anything here:

- The dashboard holds **no GitHub write access** and makes **no request** to GitHub. It is read-only
  (`GET` routes only: `test_the_api_accepts_no_writes` in `tests/unit/dashboard/test_api.py`); the
  drafting code in `reporting/issues.py` imports no HTTP client.
- A draft is a title and a Markdown body, shown on the page with **Copy draft**.
- When every supporting run belongs to **one collected repository**, the draft also has **Review and
  submit on GitHub**: a link to GitHub's own *New issue* form with title and body filled in. Opening
  it creates nothing; a person reads the draft and presses *Submit new issue* on GitHub. That
  person, signed in with their own account, is the approval.
- Runs from several repositories, or hand-imported runs without a repository, get no link: the
  draft does not guess where it belongs. Copy it instead.

## What a draft contains

| Part | Content |
|---|---|
| Title | `Recurring test failure: <signature>` (first 120 characters) |
| Signature | exception type + first message line with numbers and ids masked, in a code span |
| Counts | runs with the signature, of them in the 7 days before the newest run, occurrences, first and last seen (UTC) |
| Affected tests | up to 10 test keys in code spans, "and N more" |
| Newest supporting runs | up to 10: result file, start time, a link to the run in this dashboard (absolute: the issue lives on GitHub) and to the CI run when a collection record has its GitHub URL |
| Footer | where the rules are documented; "check the evidence before submitting" |

Imported text is never Markdown: test keys and the signature sit in code spans (backticks
removed from them), file names are escaped. A test named `[x](https://...)` stays text.

GitHub refuses very long addresses, so the pre-filled link drops evidence lines (tests and runs)
until it is shorter than 7,000 characters and says so ("The GitHub form gets a shortened evidence
list"); **Copy draft** always has the full body. If even the shortest body is too long, there is no
link, only the copy.

## On the data

The sample results and the collected TaskBoard samples have no recurring failure (no failure cause
appears in two runs), so the sample dashboard shows "No recurring failure, so nothing to draft."
Recurring causes appear in the collected history of the live deployment.

Checked by `tests/unit/test_issue_drafts.py` (content, link only with one known repository, the
form's title and body equal the draft's, shortening, escaping, rank and limit) and the issue tests
in `tests/unit/dashboard/test_api.py` (absolute dashboard link, the CI run from a collection record,
the samples have no drafts).
