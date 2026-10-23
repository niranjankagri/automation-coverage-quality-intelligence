// Test details (docs/report-ui.md): one execution of one test. The address names the execution (run)
// and its context (repository, job, browser, environment), and the details show that execution:
// never the newest run of another browser. History in this context and across all contexts are kept
// apart; evidence that was not collected is said to be missing, not left out silently.

import { api, href, query } from "./api.js";
import { badge, clock, contextLine, emptyState, formatDate, h, loadMore, n, repoName } from "./dom.js";

const TABS = [["execution", "Selected execution"], ["history", "History"], ["browsers", "Browser comparison"], ["evidence", "Evidence"]];

/** The scope of an execution, for links to it. */
const scopeOf = (e) => Object.fromEntries(Object.entries({
  repository: e.pipeline?.repository, job: e.pipeline?.repository ? e.pipeline?.job : null, browser: e.context.browser, environment: e.context.environment,
}).filter(([, value]) => value));
const linkTo = (key, e) => href("test", scopeOf(e), { key, run: e.run_id });
const where = (e) => contextLine([e.pipeline?.repository ? repoName(e.pipeline.repository) : null, e.pipeline?.job, e.context.browser, e.context.environment, e.context.platform]) || "imported file";
const sameContext = (a, b) => where(a) === where(b);

export async function testDetails(state, { signal }) {
  const key = state.params.get("key");
  const run = state.params.get("run");
  if (!key) return [h("h1", {}, "Test details"), emptyState("none", "No test was chosen.", h("a", { class: "button-quiet", href: href("results", state.scope) }, "Open Test Results"))];
  const get = (scope) => api(`/api/tests/history${query(scope, { key })}`, { signal }).catch((error) => (error.message.startsWith("404") ? null : Promise.reject(error)));
  const [inContext, everywhere] = await Promise.all([get(state.scope), get({})]);
  const back = state.from && !state.from.startsWith("#/test") ? state.from : href("results", state.scope);
  const backLink = h("a", { class: "back-link", href: back }, "← Back to results");
  if (!everywhere) return [backLink, h("h1", {}, "Test details"), emptyState("none", `No execution of ${key} is in the data.`)];

  const executions = inContext?.executions ?? [];
  let selected = run ? executions.find((e) => e.run_id === run) ?? everywhere.executions.find((e) => e.run_id === run) : executions[0];
  const missing = run && !selected;
  selected ??= executions[0] ?? everywhere.executions[0];
  const context = everywhere.executions.filter((e) => sameContext(e, selected));
  const tab = TABS.some(([id]) => id === state.params.get("tab")) ? state.params.get("tab") : "execution";

  const panels = {
    execution: () => executionPanel(selected, everywhere),
    history: () => historyPanel(key, selected, context, everywhere.executions),
    browsers: () => browsersPanel(key, selected, everywhere.executions),
    evidence: () => evidencePanel(selected),
  };
  const panel = h("div", { class: "tab-panel", role: "tabpanel", id: "test-panel", tabindex: "0" });
  const tabs = TABS.map(([id, label]) => {
    const button = h("button", { type: "button", role: "tab", id: `tab-${id}`, "aria-controls": "test-panel", "aria-selected": String(id === tab), tabindex: id === tab ? "0" : "-1" }, label);
    button.addEventListener("click", () => choose(id));
    button.addEventListener("keydown", (event) => {
      const i = TABS.findIndex(([t]) => t === id);
      const next = event.key === "ArrowRight" ? TABS[(i + 1) % TABS.length] : event.key === "ArrowLeft" ? TABS[(i + TABS.length - 1) % TABS.length] : null;
      if (next) { event.preventDefault(); choose(next[0]); document.getElementById(`tab-${next[0]}`).focus(); }
    });
    return button;
  });
  const choose = (id) => {
    for (const b of tabs) {
      const on = b.id === `tab-${id}`;
      b.setAttribute("aria-selected", String(on));
      b.tabIndex = on ? 0 : -1;
    }
    panel.setAttribute("aria-labelledby", `tab-${id}`);
    panel.replaceChildren(...[panels[id]()].flat(Infinity).filter(Boolean));
    const params = new URLSearchParams(state.params);
    params.set("tab", id);
    history.replaceState(null, "", `#/test?${params}`);
  };
  panel.setAttribute("aria-labelledby", `tab-${tab}`);
  panel.replaceChildren(...[panels[tab]()].flat(Infinity).filter(Boolean));

  return [
    backLink,
    h("p", { class: "eyebrow" }, `Test · ${selected.context.framework ?? "test"}`),
    h("h1", { class: "test-title" }, selected.name),
    h("p", { class: "detail-key" }, h("code", {}, key)),
    missing ? h("p", { class: "notice notice-warning", role: "status" }, "The execution in this address is no longer in the data; the newest one in the same context is shown.") : null,
    h("div", { class: "execution-head card" },
      h("div", { class: "detail-badges" }, badge(selected.outcome), h("strong", {}, clock(selected.duration_seconds)), h("span", { class: "sub" }, formatDate(selected.started_at))),
      h("dl", { class: "facts" },
        h("dt", {}, "Ran in"), h("dd", {}, where(selected)),
        h("dt", {}, "Commit"), h("dd", {}, selected.pipeline?.commit ? `${selected.pipeline.commit.slice(0, 7)}${selected.pipeline.branch ? ` on ${selected.pipeline.branch}` : ""}` : "not recorded"),
        h("dt", {}, "Pipeline"), h("dd", {}, selected.ci_url ? h("a", { href: selected.ci_url, rel: "noopener noreferrer", target: "_blank" }, `CI run ${selected.pipeline?.pipeline_id ?? ""}`.trim()) : selected.pipeline ? `run ${selected.pipeline.pipeline_id} (no link recorded)` : "imported file (no pipeline)"))),
    h("div", { class: "tabs", role: "tablist", "aria-label": "Test details" }, tabs),
    panel,
  ];
}

function executionPanel(e, history) {
  return [
    e.failure
      ? h("div", { class: "failure" }, h("p", { class: "failure-title" }, e.failure.type || "Failure"), h("pre", {}, e.failure.message || "(no message recorded)"))
      : h("p", { class: "sub" }, e.outcome === "passed" ? "Passed: no failure to show." : `Outcome ${e.outcome}; no failure message recorded.`),
    h("dl", { class: "facts" },
      h("dt", {}, "Outcome"), h("dd", {}, e.outcome),
      h("dt", {}, "Duration"), h("dd", {}, clock(e.duration_seconds)),
      h("dt", {}, "Retries in this run"), h("dd", {}, n(e.retries)),
      h("dt", {}, "Started"), h("dd", {}, formatDate(e.started_at)),
      h("dt", {}, "Framework"), h("dd", {}, e.context.framework ?? "not recorded"),
      h("dt", {}, "Run"), h("dd", {}, h("a", { href: `/#/run/${encodeURIComponent(e.run_id)}` }, e.run_id.slice(0, 12)))),
    h("h3", {}, "Requirements"),
    history.requirements.length
      ? h("p", {}, history.requirements.map((id, i) => [i ? ", " : null, h("a", { href: href("requirement", {}, { id }) }, id)]))
      : h("p", { class: "sub" }, history.test_cases.length ? `Test case(s) ${history.test_cases.join(", ")} link no requirement.` : "Not mapped: no requirement is linked to this test."),
  ];
}

function historyPanel(key, selected, context, all) {
  const pattern = (list) => h("ol", { class: "pattern", "aria-label": `${list.filter((e) => e.outcome === "passed").length} passed of ${list.length}, oldest first` },
    [...list].slice(0, 40).reverse().map((e) => h("li", { class: `dot dot-${e.outcome}${e.run_id === selected.run_id ? " current" : ""}`, title: `${formatDate(e.started_at)}: ${e.outcome}` })));
  const row = (e) => h("tr", { class: e.run_id === selected.run_id ? "selected" : null },
    h("td", {}, h("a", { href: linkTo(key, e) }, formatDate(e.started_at))), h("td", {}, where(e)), h("td", {}, badge(e.outcome)), h("td", { class: "num" }, clock(e.duration_seconds)));
  const table = (list, label) => loadMore(list, row, { step: 20, label, list: "tbody" });
  const wrap = (list, label) => {
    const body = table(list, label);
    const tbody = body.querySelector("tbody");
    const t = h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Started"), h("th", {}, "Context"), h("th", {}, "Result"), h("th", { class: "num" }, "Time"))));
    t.append(tbody);
    body.prepend(h("div", { class: "table-wrap" }, t));
    return body;
  };
  return [
    h("h3", {}, `In this context: ${where(selected)}`),
    pattern(context),
    h("p", { class: "sub" }, `${n(context.filter((e) => e.outcome === "passed").length)} passed of ${n(context.length)} execution(s); the selected one is outlined.`),
    wrap(context, "executions in this context"),
    h("h3", {}, "Across all contexts"),
    h("p", { class: "sub" }, `${n(all.length)} execution(s) in every repository, job and browser.`),
    wrap(all, "executions"),
  ];
}

function browsersPanel(key, selected, all) {
  const latest = new Map();
  const tally = new Map();
  for (const e of all) {
    const id = where(e);
    if (!latest.has(id)) latest.set(id, e); // executions are newest first
    const t = tally.get(id) ?? { passed: 0, total: 0 };
    t.total += 1;
    if (e.outcome === "passed") t.passed += 1;
    tally.set(id, t);
  }
  if (latest.size < 2) return [h("p", { class: "sub" }, "This test ran in one context only, so there is nothing to compare."), ...[...latest.values()].map((e) => h("p", {}, where(e)))];
  return h("div", { class: "table-wrap" }, h("table", {},
    h("thead", {}, h("tr", {}, h("th", {}, "Context"), h("th", {}, "Latest result"), h("th", { class: "num" }, "Time"), h("th", {}, "Latest run"), h("th", { class: "num" }, "Passed / runs"))),
    h("tbody", {}, [...latest.entries()].map(([id, e]) => h("tr", { class: sameContext(e, selected) ? "selected" : null },
      h("td", {}, h("a", { href: linkTo(key, e) }, id)), h("td", {}, badge(e.outcome)), h("td", { class: "num" }, clock(e.duration_seconds)),
      h("td", {}, formatDate(e.started_at)), h("td", { class: "num" }, `${n(tally.get(id).passed)} / ${n(tally.get(id).total)}`))))));
}

function evidencePanel(e) {
  return [
    h("h3", {}, "Failure output"),
    e.failure?.text || e.failure?.message
      ? h("pre", { class: "evidence" }, e.failure.text || e.failure.message)
      : h("p", { class: "sub" }, e.failure ? "The report recorded a failure without output." : "No failure output: the test did not fail in this execution."),
    h("h3", {}, "Screenshots, videos, traces and logs"),
    h("p", {}, "Not collected: Quality Intelligence reads the test reports only. ",
      e.ci_url ? ["The CI run keeps them as artifacts: ", h("a", { href: e.ci_url, rel: "noopener noreferrer", target: "_blank" }, "open the CI run"), "."] : "No CI run link was recorded for this execution."),
    h("h3", {}, "Source"),
    h("p", { class: "sub" }, `Report file: ${e.source}`),
  ];
}
