// A requirement inside the report (docs/report-ui.md): its catalog entry, its test cases and the
// executions in the chosen scope, each opening the exact execution. The scope is kept, so "Back to
// coverage" returns to the same filters.

import { api, href, query } from "./api.js";
import { badge, clock, contextLine, emptyState, formatDate, h, n, repoName } from "./dom.js";

const TONE = { passing: "passed", failing: "failed", "not run": "error", "not automated": "skipped", "no tests": "skipped" };

const scopeOf = (e) => Object.fromEntries(Object.entries({
  repository: e.pipeline?.repository, job: e.pipeline?.repository ? e.pipeline?.job : null, browser: e.context.browser, environment: e.context.environment,
}).filter(([, value]) => value));

export async function requirement(state, { signal }) {
  const id = state.params.get("id");
  const back = h("a", { class: "back-link", href: state.from && state.from.startsWith("#/coverage") ? state.from : href("coverage", state.scope) }, "← Back to coverage");
  if (!id) return [back, h("h1", {}, "Requirement"), emptyState("none", "No requirement was chosen.")];
  let d;
  try {
    d = await api(`/api/requirements/${encodeURIComponent(id)}${query(state.scope)}`, { signal });
  } catch (error) {
    if (!error.message.startsWith("404")) throw error;
    return [back, h("h1", {}, id), emptyState("none", `Requirement ${id} is not in the catalog.`)];
  }
  const r = d.requirement;
  const status = r.coverage_status === "no tests" ? "no tests" : r.coverage_status === "not automated" ? "not automated" : r.execution_status;
  return [
    back,
    h("p", { class: "eyebrow" }, `Requirement · ${r.feature || "no feature"}`),
    h("h1", {}, `${r.id} ${r.title}`),
    r.description ? h("p", { class: "lead" }, r.description) : null,
    h("div", { class: "card" },
      h("div", { class: "detail-badges" }, badge(TONE[status] ?? "skipped", status), r.stale ? badge("error", "stale evidence") : null),
      h("dl", { class: "facts" },
        h("dt", {}, "Criticality"), h("dd", {}, [r.criticality, r.priority, r.risk ? `${r.risk} risk` : null].filter(Boolean).join(" · ") || "not set"),
        h("dt", {}, "Owner"), h("dd", {}, r.owner ?? "not set"),
        h("dt", {}, "Test cases"), h("dd", {}, `${n(r.automated_test_cases)} of ${n(r.test_cases)} automated`),
        h("dt", {}, "Last executed"), h("dd", {}, r.last_executed_at ? formatDate(r.last_executed_at) : "not in this scope"),
        h("dt", {}, "Source"), h("dd", {}, "Requirements catalog (synthetic sample); executions are real CI results"))),
    h("h2", { class: "section-title" }, "Test cases"),
    d.test_cases.length
      ? d.test_cases.map((tc) => h("section", { class: "card test-case" },
          h("div", { class: "card-head" }, h("h3", {}, `${tc.id} ${tc.title}`), badge(TONE[tc.execution_status] ?? "skipped", tc.execution_status)),
          h("p", { class: "sub" }, contextLine([tc.test_type?.toUpperCase(), tc.framework, tc.automation_status])),
          tc.executions.length
            ? h("div", { class: "table-wrap" }, h("table", {},
                h("thead", {}, h("tr", {}, h("th", {}, "Test"), h("th", {}, "Ran in"), h("th", {}, "Result"), h("th", { class: "num" }, "Time"), h("th", {}, "Started"))),
                h("tbody", {}, tc.executions.map((e) => h("tr", {},
                  h("td", {}, h("a", { href: href("test", scopeOf(e), { key: e.key, run: e.run_id }) }, e.name)),
                  h("td", {}, contextLine([e.pipeline?.repository ? repoName(e.pipeline.repository) : null, e.pipeline?.job, e.context.browser]) || "imported file"),
                  h("td", {}, badge(e.outcome)), h("td", { class: "num" }, clock(e.duration_seconds)), h("td", {}, formatDate(e.started_at)))))))
            : h("p", { class: "sub" }, tc.automation_status === "automated" ? "Automated, but not run in this scope." : "Not automated: no executions expected.")))
      : emptyState("none", "No test case is linked to this requirement."),
  ];
}
