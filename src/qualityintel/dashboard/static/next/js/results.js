// Test Results (docs/report-ui.md): the latest result of every test in the scope. Unfiltered, a tree
// of repository > job > class > test; with a search or status filter, a flat list that loads more on
// request ("Showing X of Y", nothing hidden). Every test links to the exact execution shown, with its
// repository, job, browser and environment, so details never open another browser's run.

import { api, href, query } from "./api.js";
import { OUTCOMES, clock, contextLine, emptyState, h, loadMore, n, repoName } from "./dom.js";

// Results listed per "Load more" step while a filter is active
const STEP = 50;

/** The scope of one execution: what a drill-down request and its shareable address carry. */
export function executionScope(group, job) {
  const scope = {};
  if (group.collected) {
    scope.repository = group.name;
    scope.job = job.name; // only collected runs have real job names
  }
  if (job.browser) scope.browser = job.browser;
  if (job.environment) scope.environment = job.environment;
  return scope;
}

/** Link to a test's details: the execution (run) and its context. */
/** Where a test ran: repository, job and browser; for imported files the run context says it all. */
export const ranIn = (group, job) => (group.collected ? contextLine([repoName(group.name), job.name, job.browser]) : job.name);

export const testLink = (test, group, job) => href("test", executionScope(group, job), { key: test.key, run: test.run_id });

export async function results(state, { signal, facts }) {
  const scope = state.scope;
  const tree = await api(`/api/report/suites${query(scope)}`, { signal });
  const filter = { q: state.params.get("q") ?? "", statuses: new Set((state.params.get("status") || "").split(",").filter((o) => OUTCOMES.includes(o))) };
  const rows = tree.groups.flatMap((group) => group.jobs.flatMap((job) => job.classes.flatMap((cls) => cls.tests.map((test) => ({ test, cls, job, group })))));
  const totals = Object.fromEntries(OUTCOMES.map((o) => [o, rows.filter((r) => r.test.outcome === o).length]));
  const box = h("div", { class: "results-body" });

  // The filter lives in the address (replaced, not pushed: typing is not a navigation)
  const remember = () => history.replaceState(null, "", href("results", scope, { q: filter.q, status: [...filter.statuses].join(",") }));
  const draw = () => box.replaceChildren(filter.q || filter.statuses.size ? flatList(rows, filter) : treeView(tree));

  const search = h("input", { type: "search", class: "search", placeholder: "Search test, class or job", "aria-label": "Search tests", value: filter.q });
  let timer = 0;
  search.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => { filter.q = search.value.trim(); remember(); draw(); }, 200);
  });
  const chips = OUTCOMES.map((outcome) => {
    const chip = h("button", { type: "button", class: "chip", "aria-pressed": String(filter.statuses.has(outcome)) },
      h("span", { class: `dot dot-${outcome}`, "aria-hidden": "true" }), outcome, h("span", { class: "chip-count" }, n(totals[outcome])));
    chip.addEventListener("click", () => {
      if (filter.statuses.has(outcome)) filter.statuses.delete(outcome);
      else filter.statuses.add(outcome);
      chip.setAttribute("aria-pressed", String(filter.statuses.has(outcome)));
      remember();
      draw();
    });
    return chip;
  });
  draw();

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(scope.repository)}`),
    h("h1", {}, "Test Results"),
    h("p", { class: "lead" }, "The latest result of every test in this scope, by repository, job and class. Select a test for its details."),
    tree.total === 0
      ? emptyState(facts.health?.runs === 0 ? "no-data" : "no-match", null, Object.keys(scope).length ? h("a", { class: "button-quiet", href: href("results", {}) }, "Clear the filters") : null)
      : h("section", { class: "card results-card", "aria-label": "Test results" },
          h("div", { class: "toolbar" }, search, h("div", { class: "chips", role: "group", "aria-label": "Show only these results" }, chips)),
          box),
  ];
}

/** Repository > job > class > test; classes fill when opened, so large scopes stay quick. */
function treeView(tree) {
  const counts = (c) => h("span", { class: "node-counts" }, OUTCOMES.filter((o) => c[o]).map((o) => h("span", { class: `count-${o}`, title: `${c[o]} ${o}` }, n(c[o]))));
  const node = (label, sub, c, open, fill) => {
    const details = h("details", { class: "node", open: open ? "" : null },
      h("summary", {}, h("span", { class: "node-label" }, label, sub ? h("small", {}, sub) : null), counts(c)));
    const build = () => {
      if (!details.dataset.filled) details.append(...[fill()].flat());
      details.dataset.filled = "1";
    };
    if (open) build();
    else details.addEventListener("toggle", () => details.open && build());
    return details;
  };
  const single = tree.groups.length === 1;
  return h("div", { class: "tree" }, tree.groups.map((group) =>
    node(group.collected ? repoName(group.name) : group.name, group.collected ? group.name : "imported files (not collected)", group.counts, single, () =>
      group.jobs.map((job) => node(job.name, contextLine([job.browser, job.environment, job.platform]) || null, job.counts, single && group.jobs.length === 1, () =>
        job.classes.map((cls) => node(cls.name, null, cls.counts, single && group.jobs.length === 1 && job.classes.length === 1, () =>
          cls.tests.map((test) => testRow(test, group, job, null)))))))));
}

/** Every matching test of the scope, flat, 50 at a time. */
function flatList(rows, filter) {
  const q = filter.q.toLowerCase();
  const matches = rows.filter(({ test, cls, job }) =>
    (!filter.statuses.size || filter.statuses.has(test.outcome)) &&
    (!q || test.name.toLowerCase().includes(q) || cls.name.toLowerCase().includes(q) || job.name.toLowerCase().includes(q)));
  if (!matches.length) return emptyState("no-match", "No test in this scope matches the search and status filter.");
  return loadMore(matches, ({ test, cls, job, group }) => testRow(test, group, job, cls), { step: STEP, label: "matching results", list: "ul", listClass: "flat-list" });
}

/** One test: outcome, name, where it ran (in the flat list) and its time; links to its details. */
function testRow(test, group, job, cls) {
  const where = cls ? contextLine([ranIn(group, job), cls.name]) : null;
  const time = test.retries ? `${clock(test.duration_seconds)} · ${test.retries} retr${test.retries === 1 ? "y" : "ies"}` : clock(test.duration_seconds);
  return h(cls ? "li" : "div", { class: "test-item" },
    h("a", { class: "test-row", href: testLink(test, group, job), "data-key": test.key },
      h("span", { class: `dot dot-${test.outcome}`, role: "img", "aria-label": test.outcome }),
      h("span", { class: "test-name" }, test.name, where ? h("small", {}, where) : null),
      h("span", { class: "test-time" }, time)));
}
