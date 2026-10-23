// Categories: Allure's failure categories (docs/report-ui.md). Three questions, most urgent first:
// what fails now and why (the latest snapshot grouped by cause), which tests are unstable over the
// recent history, and which causes keep coming back (with an issue draft). Every test opens in Suites.

import { api, scopeQuery } from "./api.js";
import { formatDate, h, n, repoName } from "./dom.js";

// Unstable statuses in the order a reader acts on them (history/analysis.py, Stability)
const UNSTABLE = [
  { status: "consistently failing", label: "Consistently failing", tone: "failed", what: "the last verdicts all failed" },
  { status: "new failure", label: "New failures", tone: "failed", what: "failed now after passing" },
  { status: "flaky candidate", label: "Flaky candidates", tone: "error", what: "mixed results without a code change" },
  { status: "recovered", label: "Recovered", tone: "passed", what: "failed in the window, passes now" },
];
// Tests listed per group before "and N more"
const TESTS_SHOWN = 8;

export async function categories(state) {
  const scope = scopeQuery(state.repository);
  const [overview, stability, issues] = await Promise.all([
    api(`/api/report/overview${scope}`),
    api(`/api/stability${scope}`),
    api(`/api/issue-suggestions${scopeQuery(state.repository, { limit: 10 })}`),
  ]);
  const suiteLink = (key) => `#/suites${scopeQuery(state.repository, { test: key })}`;
  const testList = (keys) => h("ul", { class: "cat-tests" },
    keys.slice(0, TESTS_SHOWN).map((key) => h("li", {}, h("a", { href: suiteLink(key) }, shortKey(key)))),
    keys.length > TESTS_SHOWN ? h("li", { class: "sub" }, `and ${n(keys.length - TESTS_SHOWN)} more`) : null);

  const failingNow = overview.categories;
  const unstable = UNSTABLE.map((kind) => ({ ...kind, rows: stability.rows.filter((r) => r.status === kind.status) }));
  const unstableTotal = unstable.reduce((sum, kind) => sum + kind.rows.length, 0);
  const drafts = new Map(issues.drafts.map((d) => [d.signature, d]));

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(state.repository)}`),
    h("h1", {}, "Categories"),
    h("p", { class: "lead" }, "Failures grouped by cause: what fails now, what is unstable, and what keeps coming back."),
    h("div", { class: "cat-summary" },
      stat(failingNow.reduce((sum, c) => sum + c.results, 0), "failing results now", failingNow.length ? "failed" : "passed"),
      stat(unstableTotal, "unstable tests", unstableTotal ? "error" : "passed"),
      stat(stability.recurring_failures.length, "recurring causes", stability.recurring_failures.length ? "failed" : "passed")),

    h("section", { class: "card cat-section", "aria-labelledby": "cat-now" },
      h("div", { class: "card-head" }, h("h2", { id: "cat-now" }, "Failing now"),
        h("span", { class: "meta" }, `${n(failingNow.length)} cause(s) in the latest results`)),
      failingNow.length
        ? failingNow.map((c) => h("details", { class: `cat cat-${c.outcome}` },
            h("summary", {},
              h("span", { class: `badge badge-${c.outcome}` }, c.outcome === "failed" ? "product defect" : "broken"),
              h("span", { class: "cat-signature" }, c.signature),
              h("span", { class: "cat-count" }, `${n(c.results)} result(s)`)),
            testList(c.tests)))
        : h("p", { class: "empty" }, "Nothing fails in the latest results.")),

    h("section", { class: "card cat-section", "aria-labelledby": "cat-unstable" },
      h("div", { class: "card-head" }, h("h2", { id: "cat-unstable" }, "Unstable tests"),
        h("span", { class: "meta" }, `last ${n(stability.window)} verdicts per test and context`)),
      unstableTotal
        ? unstable.filter((kind) => kind.rows.length).map((kind) => h("details", { class: `cat cat-${kind.tone}`, open: kind.tone === "failed" ? "" : null },
            h("summary", {},
              h("span", { class: `badge badge-${kind.tone}` }, kind.label),
              h("span", { class: "cat-what" }, kind.what),
              h("span", { class: "cat-count" }, `${n(kind.rows.length)} test(s)`)),
            h("ul", { class: "cat-tests" }, kind.rows.slice(0, TESTS_SHOWN * 2).map((row) => h("li", {},
              h("a", { href: suiteLink(row.key) }, shortKey(row.key)),
              h("span", { class: "sub" }, ` · ${row.context} · ${row.failure_rate.text} failed${row.reasons.length ? ` · ${row.reasons[0]}` : ""}`))),
              kind.rows.length > TESTS_SHOWN * 2 ? h("li", { class: "sub" }, `and ${n(kind.rows.length - TESTS_SHOWN * 2)} more`) : null)))
        : h("p", { class: "empty" }, "Every test with enough history is stable.")),

    h("section", { class: "card cat-section", "aria-labelledby": "cat-recurring" },
      h("div", { class: "card-head" }, h("h2", { id: "cat-recurring" }, "Recurring causes"),
        h("span", { class: "meta" }, "the same failure in more than one run")),
      stability.recurring_failures.length
        ? stability.recurring_failures.map((r) => {
            const draft = drafts.get(r.signature);
            return h("details", { class: "cat cat-failed" },
              h("summary", {},
                h("span", { class: "badge badge-failed" }, `${n(r.runs)} runs`),
                h("span", { class: "cat-signature" }, r.signature),
                h("span", { class: "cat-count" }, `last ${formatDate(r.last_seen, false)}`)),
              h("p", { class: "sub" }, `${n(r.occurrences)} failure(s) in ${n(r.runs)} run(s), ${n(r.recent_runs)} recently; first seen ${formatDate(r.first_seen, false)}.`),
              testList(r.tests),
              draft
                ? h("p", {}, draft.new_issue_url
                    ? h("a", { class: "button", href: draft.new_issue_url, rel: "noopener noreferrer", target: "_blank" }, "Draft a GitHub issue")
                    : h("span", { class: "sub" }, "Issue draft ready in the classic dashboard (runs span several repositories)."))
                : null);
          })
        : h("p", { class: "empty" }, "No failure cause has repeated across runs.")),
  ];
}

const stat = (value, label, tone) => h("div", { class: `cat-stat stat-${tone}` }, h("strong", {}, n(value)), h("span", {}, label));

/** "e2e/api/auth.cy.ts::test" reads as "auth › test", "com.x.LoginTest::test" as "LoginTest › test". */
const shortKey = (key) => {
  const [where, name] = key.split("::");
  if (!name) return key;
  const file = where.includes("/") ? where.split("/").at(-1).split(".")[0] : where.split(".").at(-1);
  return `${file} › ${name}`;
};
