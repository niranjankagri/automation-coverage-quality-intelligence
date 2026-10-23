// Suites: Allure's two panes (docs/report-ui.md). Left, the latest snapshot as a tree (repository >
// job > class > test) with a name filter and status chips; right, the selected test's details from its
// history. The selection lives in the address (#/suites?test=...), so a test's page can be shared.

import { api, scopeQuery } from "./api.js";
import { OUTCOMES, formatDate, h, n, repoName } from "./dom.js";

// Tests rendered at most while a filter is active (the counts cover all of them)
const MATCH_LIMIT = 400;
// Executions shown in a test's history (newest first)
const HISTORY_ROWS = 20;

const seconds = (value) => (value === null || value === undefined ? "–" : value < 1 ? `${Math.round(value * 1000)} ms` : `${value.toFixed(value < 10 ? 2 : 1)} s`);

export async function suites(state) {
  const tree = await api(`/api/report/suites${scopeQuery(state.repository)}`);
  const params = state.params;
  const filter = { q: params.get("q") ?? "", statuses: new Set((params.get("status") || "").split(",").filter(Boolean)) };
  const detail = h("section", { class: "card suite-detail", "aria-live": "polite", "aria-label": "Selected test" });
  const treeBox = h("div", { class: "tree" });
  const counter = h("p", { class: "tree-count", role: "status" });

  const select = async (key, push = true) => {
    for (const button of treeBox.querySelectorAll(".test-row[aria-current]")) button.removeAttribute("aria-current");
    treeBox.querySelector(`.test-row[data-key="${CSS.escape(key)}"]`)?.setAttribute("aria-current", "true");
    if (push) {
      const next = new URLSearchParams(params);
      next.set("test", key);
      history.pushState(null, "", `#/suites?${next}`);
    }
    detail.replaceChildren(h("p", { class: "loading" }, "Loading the test…"));
    try {
      // Optional parts are null: replaceChildren would print them as text
      const parts = testDetails(await api(`/api/tests/history${scopeQuery(state.repository, { key })}`));
      detail.replaceChildren(...parts.filter((part) => part !== null));
    } catch (error) {
      detail.replaceChildren(h("p", { class: "error-box", role: "alert" }, `Could not load this test: ${error.message}`));
    }
    if (window.matchMedia("(max-width: 900px)").matches) detail.scrollIntoView({ block: "start" });
  };

  const draw = () => {
    const shown = renderTree(tree, filter, params.get("test"), select);
    treeBox.replaceChildren(...shown.nodes);
    counter.textContent = filter.q || filter.statuses.size
      ? `${n(shown.matches)} of ${n(tree.total)} tests match${shown.matches > MATCH_LIMIT ? `, the first ${MATCH_LIMIT} are listed` : ""}`
      : `${n(tree.total)} tests`;
  };

  const search = h("input", { type: "search", class: "tree-search", placeholder: "Filter by test or class name", "aria-label": "Filter tests by name", value: filter.q });
  search.addEventListener("input", () => {
    filter.q = search.value.trim();
    draw();
  });
  const chips = OUTCOMES.map((outcome) => {
    const total = tree.groups.reduce((sum, g) => sum + g.counts[outcome], 0);
    const chip = h("button", { type: "button", class: `chip chip-${outcome}`, "aria-pressed": String(filter.statuses.has(outcome)) },
      h("span", { class: `dot dot-${outcome}`, "aria-hidden": "true" }), `${outcome} `, h("span", { class: "chip-count" }, n(total)));
    chip.addEventListener("click", () => {
      if (filter.statuses.has(outcome)) filter.statuses.delete(outcome);
      else filter.statuses.add(outcome);
      chip.setAttribute("aria-pressed", String(filter.statuses.has(outcome)));
      draw();
    });
    return chip;
  });

  draw();
  if (params.get("test")) select(params.get("test"), false);
  else detail.replaceChildren(h("div", { class: "detail-empty" }, h("h2", {}, "Select a test"),
    h("p", {}, "Choose a test in the tree to see its latest result, failure, history and linked requirements."),
    h("p", { class: "sub" }, "Tip: use the status chips to list only the failed or error tests.")));

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(state.repository)}`),
    h("h1", {}, "Suites"),
    h("p", { class: "lead" }, "The latest result of every test, by repository, job and class. Select a test for its details."),
    h("div", { class: "split" },
      h("section", { class: "card tree-pane", "aria-label": "Test tree" },
        h("div", { class: "tree-tools" }, search, h("div", { class: "chips", role: "group", "aria-label": "Show only these results" }, chips), counter),
        treeBox),
      detail),
  ];
}

/** The tree as nested <details>; with a filter, only matching tests and their parents (opened). */
function renderTree(tree, filter, selected, select) {
  const q = filter.q.toLowerCase();
  const filtering = Boolean(q || filter.statuses.size);
  const keep = (test, className) =>
    (!filter.statuses.size || filter.statuses.has(test.outcome)) &&
    (!q || test.name.toLowerCase().includes(q) || className.toLowerCase().includes(q));
  let matches = 0;
  const testRow = (test) => {
    const row = h("button", { type: "button", class: "test-row", "data-key": test.key, "aria-current": test.key === selected ? "true" : null, title: test.key },
      h("span", { class: `dot dot-${test.outcome}`, role: "img", "aria-label": test.outcome }),
      h("span", { class: "test-name" }, test.name),
      h("span", { class: "test-time" }, test.retries ? `${seconds(test.duration_seconds)} · ${test.retries} retr${test.retries === 1 ? "y" : "ies"}` : seconds(test.duration_seconds)));
    row.addEventListener("click", () => select(test.key));
    return row;
  };
  const bar = (counts) => h("span", { class: "node-counts" }, OUTCOMES.filter((o) => counts[o]).map((o) => h("span", { class: `count-${o}`, title: `${counts[o]} ${o}` }, n(counts[o]))));
  const node = (label, sub, counts, open, children, lazy = null) => {
    const details = h("details", { class: "node", open: open ? "" : null },
      h("summary", {}, h("span", { class: "node-label" }, label, sub ? h("small", {}, sub) : null), bar(counts)),
      ...(lazy ? [] : children));
    if (lazy) {
      // Big classes are built when first opened, so a large tree stays quick
      const fill = () => {
        if (!details.dataset.filled) details.append(...lazy());
        details.dataset.filled = "1";
      };
      if (open) fill();
      else details.addEventListener("toggle", () => details.open && fill(), { once: false });
    }
    return details;
  };

  const groups = [];
  for (const group of tree.groups) {
    // A node that is the only one under an open parent opens too: no clicking through single levels
    const groupOpen = tree.groups.length === 1;
    const jobs = [];
    for (const job of group.jobs) {
      const classes = [];
      for (const cls of job.classes) {
        const tests = filtering ? cls.tests.filter((t) => keep(t, cls.name)) : cls.tests;
        if (filtering && !tests.length) continue;
        const holdsSelected = tests.some((t) => t.key === selected);
        if (filtering) {
          const room = Math.max(0, MATCH_LIMIT - matches);
          matches += tests.length;
          if (!room) continue;
          classes.push(node(cls.name, null, cls.counts, true, tests.slice(0, room).map(testRow)));
        } else {
          const only = groupOpen && group.jobs.length === 1 && job.classes.length === 1;
          classes.push(node(cls.name, null, cls.counts, holdsSelected || only, null, () => tests.map(testRow)));
        }
      }
      if (filtering && !classes.length) continue;
      const holds = job.classes.some((c) => c.tests.some((t) => t.key === selected));
      const only = groupOpen && group.jobs.length === 1;
      jobs.push(node(job.name, job.name === job.context ? null : job.context, job.counts, filtering || holds || only, classes));
    }
    if (filtering && !jobs.length) continue;
    const holds = group.jobs.some((j) => j.classes.some((c) => c.tests.some((t) => t.key === selected)));
    groups.push(node(group.collected ? repoName(group.name) : group.name, null, group.counts, filtering || holds || groupOpen, jobs));
  }
  if (!groups.length) groups.push(h("p", { class: "empty" }, filtering ? "No test matches this filter." : "No tests in this scope."));
  return { nodes: groups, matches: filtering ? matches : tree.total };
}

/** The selected test: latest result, failure, history pattern and executions, requirements. */
function testDetails(d) {
  const latest = d.executions[0];
  const oldestFirst = [...d.executions].slice(0, 40).reverse();
  return [
    h("p", { class: "eyebrow" }, latest.context.framework ?? "test"),
    h("h2", { class: "detail-title" }, latest.name),
    h("p", { class: "detail-key" }, h("code", {}, d.key)),
    h("div", { class: "detail-badges" },
      h("span", { class: `badge badge-${latest.outcome}` }, latest.outcome),
      h("span", { class: "sub" }, `${seconds(latest.duration_seconds)} · ${formatDate(latest.started_at)}`),
      latest.retries ? h("span", { class: "sub" }, `${latest.retries} retr${latest.retries === 1 ? "y" : "ies"} in this run`) : null),
    latest.failure
      ? h("div", { class: "failure" }, h("p", { class: "failure-title" }, latest.failure.type || "Failure"),
          h("pre", {}, latest.failure.message || latest.failure.text || "(no message recorded)"))
      : null,
    h("h3", {}, "History"),
    h("ol", { class: "pattern", "aria-label": `${d.passed} passed, ${d.failed} failed or errored of ${d.executions.length} executions, oldest first` },
      oldestFirst.map((e) => h("li", { class: `dot dot-${e.outcome}`, title: `${formatDate(e.started_at)}: ${e.outcome}` }))),
    h("p", { class: "sub" }, `${d.passed} passed, ${d.failed} failed or errored of ${d.executions.length} executions (oldest first, at most 40 shown).`),
    d.stability.length ? h("ul", { class: "stability" }, d.stability.map((line) => h("li", {}, line))) : null,
    h("details", { class: "numbers" }, h("summary", {}, `Executions (${Math.min(d.executions.length, HISTORY_ROWS)} newest)`),
      h("table", {},
        h("thead", {}, h("tr", {}, h("th", {}, "Started"), h("th", {}, "Context"), h("th", {}, "Result"), h("th", { class: "num" }, "Time"), h("th", {}, "Evidence"))),
        h("tbody", {}, d.executions.slice(0, HISTORY_ROWS).map((e) => h("tr", {},
          h("td", {}, formatDate(e.started_at)),
          h("td", {}, [e.context.framework, e.context.browser, e.pipeline?.job].filter(Boolean).join(" · ") || "–"),
          h("td", {}, h("span", { class: `badge badge-${e.outcome}` }, e.outcome)),
          h("td", { class: "num" }, seconds(e.duration_seconds)),
          h("td", {}, h("a", { href: `/#/run/${encodeURIComponent(e.run_id)}` }, "run"), e.ci_url ? [" · ", h("a", { href: e.ci_url, rel: "noopener noreferrer", target: "_blank" }, "CI run")] : null),
        ))))),
    h("h3", {}, "Requirements"),
    d.requirements.length
      ? h("p", {}, d.requirements.map((id, i) => [i ? ", " : null, h("a", { href: `/#/requirement/${encodeURIComponent(id)}` }, id)]))
      : h("p", { class: "sub" }, d.test_cases.length ? `Test case(s) ${d.test_cases.join(", ")} link no requirement.` : "No requirement is linked to this test."),
  ];
}
