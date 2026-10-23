// Failures & Stability (docs/report-ui.md): what fails now and why (the latest results grouped by
// cause), which tests are unstable over the recent history, which recovered (shown, not counted as
// unstable), and which causes keep coming back. A failed check is not called a product defect: it
// can be the product, the test or the environment, and the cause tells which.

import { api, href, query } from "./api.js";
import { badge, card, emptyState, formatDate, h, loadMore, n, repoName } from "./dom.js";

// Unstable statuses in the order a reader acts on them (history/analysis.py, Stability)
const UNSTABLE = [
  ["consistently failing", "Consistently failing", "failed", "the last verdicts all failed"],
  ["new failure", "New failures", "failed", "failed now after passing"],
  ["flaky candidate", "Flaky candidates", "error", "mixed results without a code change"],
];

/** "e2e/api/auth.cy.ts::test" reads as "auth › test", "com.x.LoginTest::test" as "LoginTest › test". */
export const shortKey = (key) => {
  const [where, name] = key.split("::");
  if (!name) return key;
  const file = where.includes("/") ? where.split("/").at(-1).split(".")[0] : where.split(".").at(-1);
  return `${file} › ${name}`;
};

export async function failures(state, { signal }) {
  const scope = state.scope;
  const q = query(scope);
  const [overview, stability, issues] = await Promise.all([
    api(`/api/report/overview${q}`, { signal }),
    api(`/api/stability${q}`, { signal }),
    api(`/api/issue-suggestions${query(scope, { limit: 10 })}`, { signal }),
  ]);
  const testHref = (key, run = null) => href("test", scope, { key, run });
  const testItem = (key) => h("li", {}, h("a", { href: testHref(key) }, shortKey(key)));
  const failingNow = overview.categories;
  const unstable = UNSTABLE.map(([status, label, tone, what]) => ({ status, label, tone, what, rows: stability.rows.filter((r) => r.status === status) }));
  const unstableCount = unstable.reduce((sum, kind) => sum + kind.rows.length, 0);
  const recovered = stability.rows.filter((r) => r.status === "recovered");
  const drafts = new Map(issues.drafts.map((d) => [d.signature, d]));
  const stabilityRow = (row) => h("li", {},
    h("a", { href: testHref(row.key, row.last_failing_run_id) }, shortKey(row.key)),
    h("span", { class: "sub" }, ` · ${row.context} · ${row.failure_rate.text} failed${row.reasons.length ? ` · ${row.reasons[0]}` : ""}`));

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(scope.repository)}`),
    h("h1", {}, "Failures & Stability"),
    h("p", { class: "lead" }, "What fails now and why, what is unstable over the recent history, and what keeps coming back."),
    h("div", { class: "stat-row" },
      stat(failingNow.reduce((sum, c) => sum + c.results, 0), "failing results now", "failed"),
      stat(unstableCount, "unstable tests", "error"),
      stat(recovered.length, "recovered (not counted as unstable)", "passed"),
      stat(stability.recurring_failures.length, "recurring causes", "failed")),

    card("f-now", "Failing now", `${n(failingNow.length)} cause(s) in the latest results`,
      failingNow.length
        ? [h("p", { class: "sub" }, "Failed: a check or assertion did not hold; the cause shows whether the product, the test or the environment is at fault. Error: the test could not run as written."),
           failingNow.map((c) => h("details", { class: "cat" },
             h("summary", {}, badge(c.outcome, c.outcome === "failed" ? "failed check" : "error"), h("span", { class: "cat-signature" }, c.signature), h("span", { class: "cat-count" }, `${n(c.results)} result(s)`)),
             loadMore(c.tests, testItem, { step: 10, label: "tests", listClass: "cat-tests" })))]
        : emptyState("no-failures"),
      { class: "section-card" }),

    card("f-unstable", "Unstable tests", `last ${n(stability.window)} verdicts per test and context`,
      unstableCount
        ? unstable.filter((kind) => kind.rows.length).map((kind) => h("details", { class: "cat", open: kind.tone === "failed" ? "" : null },
            h("summary", {}, badge(kind.tone, kind.label), h("span", { class: "cat-what" }, kind.what), h("span", { class: "cat-count" }, `${n(kind.rows.length)} test(s)`)),
            loadMore(kind.rows, stabilityRow, { step: 15, label: "tests", listClass: "cat-tests" })))
        : emptyState("stable"),
      { class: "section-card" }),

    recovered.length
      ? card("f-recovered", "Recovered", "failed in the window, passes now: not counted as unstable",
          loadMore(recovered, stabilityRow, { step: 15, label: "tests", listClass: "cat-tests" }), { class: "section-card" })
      : null,

    card("f-recurring", "Recurring causes", "the same failure in more than one run",
      stability.recurring_failures.length
        ? stability.recurring_failures.map((r) => {
            const draft = drafts.get(r.signature);
            return h("details", { class: "cat" },
              h("summary", {}, badge("failed", `${n(r.runs)} runs`), h("span", { class: "cat-signature" }, r.signature), h("span", { class: "cat-count" }, `last ${formatDate(r.last_seen, false)}`)),
              h("p", { class: "sub" }, `${n(r.occurrences)} failure(s) in ${n(r.runs)} run(s), ${n(r.recent_runs)} recently; first seen ${formatDate(r.first_seen, false)}.`),
              loadMore(r.tests, testItem, { step: 10, label: "tests", listClass: "cat-tests" }),
              draft
                ? h("p", {}, draft.new_issue_url
                    ? h("a", { class: "button", href: draft.new_issue_url, rel: "noopener noreferrer", target: "_blank" }, "Draft a GitHub issue")
                    : h("span", { class: "sub" }, "Issue draft in the classic dashboard (runs span several repositories)."))
                : null);
          })
        : emptyState("no-recurring"),
      { class: "section-card" }),
  ];
}

const stat = (value, label, tone) => h("div", { class: `stat stat-${value ? tone : "quiet"}` }, h("strong", {}, n(value)), h("span", {}, label));
