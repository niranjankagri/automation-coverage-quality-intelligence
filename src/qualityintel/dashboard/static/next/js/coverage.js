// Coverage & Requirements (docs/report-ui.md): product > feature > requirement from the catalog,
// each with what the tests in this scope show. Automation coverage is not the pass rate: it counts
// automated test cases. The catalog is the synthetic sample one; filters narrow the execution
// evidence (what ran), never which requirements exist, and the page says so.

import { api, href, query } from "./api.js";
import { badge, card, emptyState, h, n, repoName } from "./dom.js";
import { coverageOf } from "./overview.js";

const ORDER = ["failing", "not run", "no tests", "not automated", "covered"];
const LABEL = { failing: "failing", "not run": "not run here", "no tests": "no tests", "not automated": "not automated", covered: "passing" };
const TONE = { failing: "failed", "not run": "error", "no tests": "skipped", "not automated": "skipped", covered: "passed" };
const statusOf = (r) => (coverageOf(r) === "covered" && r.execution_status === "failing" ? "failing" : coverageOf(r));

export async function coverage(state, { signal }) {
  const scope = state.scope;
  const q = query(scope);
  const [summary, requirements, gaps, overview] = await Promise.all([
    api(`/api/summary${q}`, { signal }), api(`/api/requirements${q}`, { signal }), api(`/api/gaps${q}`, { signal }), api(`/api/report/overview${q}`, { signal }),
  ]);
  const scoped = Object.keys(scope).length > 0;
  const ran = requirements.filter((r) => coverageOf(r) === "covered").length;
  const notRun = requirements.filter((r) => coverageOf(r) === "not run").length;
  const openProduct = state.params.get("product");
  const reqHref = (id) => href("requirement", scope, { id });

  const products = new Map();
  for (const r of requirements) {
    const [product, ...rest] = (r.feature || "Unassigned").split(" / ");
    const feature = rest.join(" / ") || "General";
    const features = products.get(product) ?? new Map();
    products.set(product, features);
    features.set(feature, [...(features.get(feature) ?? []), r]);
  }
  const tally = (list) => {
    const found = {};
    for (const r of list) found[statusOf(r)] = (found[statusOf(r)] ?? 0) + 1;
    return h("span", { class: "node-counts" }, ORDER.filter((key) => found[key]).map((key) => h("span", { class: `count-${TONE[key]}` }, `${n(found[key])} ${LABEL[key]}`)));
  };
  const node = (label, list, open, children) => h("details", { class: "node", open: open ? "" : null },
    h("summary", {}, h("span", { class: "node-label" }, label, h("small", {}, `${n(list.length)} requirement(s)`)), tally(list)), children);
  const row = (r) => h("li", { class: "req-row" },
    badge(TONE[statusOf(r)], LABEL[statusOf(r)]),
    h("span", { class: "req-text" }, h("a", { href: reqHref(r.id) }, r.id), ` ${r.title}`),
    h("span", { class: "req-meta" }, [r.criticality, `${n(r.automated_test_cases)}/${n(r.test_cases)} test cases automated`, r.owner].filter(Boolean).join(" · ")));
  const sorted = (list) => [...list].sort((a, b) => ORDER.indexOf(statusOf(a)) - ORDER.indexOf(statusOf(b)) || a.id.localeCompare(b.id));
  const tree = [...products.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([product, features]) =>
    node(product, [...features.values()].flat(), products.size === 1 || product === openProduct,
      [...features.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([feature, list]) =>
        node(feature, list, product === openProduct, h("ul", { class: "req-list" }, sorted(list).map(row))))));

  const tile = (value, label, tone, link = null) => h(link ? "a" : "div", { class: `stat stat-${tone}`, href: link }, h("strong", {}, value), h("span", {}, label));
  const gapsCard = card("c-gaps", "Gaps by owner", `${n(gaps.total)} to close, riskiest first`,
    gaps.owners.length
      ? gaps.owners.map((owner) => h("div", { class: "owner" },
          h("h3", {}, owner.owner, h("span", { class: "sub" }, ` · ${n(owner.gaps.length)}`)),
          h("ol", { class: "rank" }, owner.gaps.map((g) => h("li", {},
            h("span", {}, h("a", { href: reqHref(g.requirement_id) }, g.requirement_id), ` ${g.title}`),
            h("span", { class: "rank-value" }, [g.kind, g.criticality].filter(Boolean).join(" · ")))))))
      : emptyState("none", "Every requirement has automated tests."),
    { class: "span-5 accent-amber", id: "gaps" });

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(scope.repository)}`),
    h("h1", {}, "Coverage & Requirements"),
    h("p", { class: "lead" }, "What the product should do, by product and feature, and whether the tests in this scope show it works."),
    h("p", { class: "notice" }, `Requirements come from the synthetic sample catalog (${n(summary.requirements_total)} requirements); the test executions are real CI results.`,
      scoped ? " The filters narrow the execution evidence (which requirements ran here), not which requirements exist." : null),
    scoped && overview.total > 0 && ran === 0 ? emptyState("not-mapped", `This scope has ${n(overview.total)} result(s), but none of them is linked to a requirement.`) : null,
    h("div", { class: "stat-row" },
      tile(summary.requirement_coverage.denominator ? summary.requirement_coverage.text : "Not mapped", "requirements with test cases", summary.requirements_without_tests.length ? "error" : "passed"),
      tile(summary.automation_coverage.denominator ? summary.automation_coverage.text : "Not mapped", "test cases automated", summary.requirements_without_automation.length ? "error" : "passed"),
      tile(n(notRun), "automated but not run in this scope", notRun ? "error" : "passed"),
      tile(n(summary.uncovered_critical.length), "critical without automated tests", summary.uncovered_critical.length ? "failed" : "passed", href("coverage", scope, { show: "gaps" }))),
    h("div", { class: "grid" },
      card("c-tree", "Features", `${n(requirements.length)} requirement(s)`,
        requirements.length ? h("div", { class: "tree coverage-tree" }, tree) : emptyState("not-mapped", "No requirements in the catalog."),
        { class: "span-7 accent-indigo" }),
      gapsCard),
  ];
}
