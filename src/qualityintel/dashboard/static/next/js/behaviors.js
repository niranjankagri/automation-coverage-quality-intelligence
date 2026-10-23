// Behaviors: Allure's behaviors view on the requirement catalog (docs/report-ui.md). Product > feature >
// requirement, each with its latest status, plus the coverage figures and what each owner should
// automate next. A requirement opens its classic page (test cases, results, history).

import { api, scopeQuery } from "./api.js";
import { h, n, repoName } from "./dom.js";

// Requirement execution statuses in the order a reader acts on them, with the colour they take
const STATUS_ORDER = ["failing", "not run", "no tests", "not automated", "passing"];
const toneOf = (status) => (status === "passing" ? "passed" : status === "failing" ? "failed" : status === "not run" ? "error" : "skipped");

export async function behaviors(state) {
  const scope = scopeQuery(state.repository);
  const [summary, requirements, gaps] = await Promise.all([
    api(`/api/summary${scope}`),
    api(`/api/requirements${scope}`),
    api(`/api/gaps${scope}`),
  ]);

  // "Toolshop / Checkout" is product "Toolshop", feature "Checkout"
  const products = new Map();
  for (const r of requirements) {
    const [product, ...rest] = (r.feature || "Unassigned").split(" / ");
    const feature = rest.join(" / ") || "General";
    const features = products.get(product) ?? new Map();
    products.set(product, features);
    features.set(feature, [...(features.get(feature) ?? []), r]);
  }
  const status = (r) => (r.coverage_status === "no tests" ? "no tests" : r.execution_status);
  const tally = (list) => {
    const found = {};
    for (const r of list) found[status(r)] = (found[status(r)] ?? 0) + 1;
    return h("span", { class: "node-counts" }, STATUS_ORDER.filter((s) => found[s])
      .map((s) => h("span", { class: `count-${toneOf(s)}`, title: `${found[s]} ${s}` }, `${n(found[s])} ${s}`)));
  };
  const node = (label, list, open, children) => h("details", { class: "node", open: open ? "" : null },
    h("summary", {}, h("span", { class: "node-label" }, label, h("small", {}, `${n(list.length)} requirement(s)`)), tally(list)), children);
  const row = (r) => h("li", { class: "req-row" },
    h("span", { class: `badge badge-${toneOf(status(r))}` }, status(r)),
    h("span", { class: "req-text" }, h("a", { href: `/#/requirement/${encodeURIComponent(r.id)}` }, r.id), ` ${r.title}`),
    h("span", { class: "req-meta" }, [r.criticality, `${n(r.automated_test_cases)}/${n(r.test_cases)} automated`].filter(Boolean).join(" · ")));

  const sorted = (list) => [...list].sort((a, b) => STATUS_ORDER.indexOf(status(a)) - STATUS_ORDER.indexOf(status(b)) || a.id.localeCompare(b.id));
  const tree = [...products.entries()].sort(([a], [b]) => a.localeCompare(b)).map(([product, features]) => {
    const all = [...features.values()].flat();
    return node(product, all, products.size === 1, [...features.entries()].sort(([a], [b]) => a.localeCompare(b))
      .map(([feature, list]) => node(feature, list, false, h("ul", { class: "req-list" }, sorted(list).map(row)))));
  });

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(state.repository)}`),
    h("h1", {}, "Behaviors"),
    h("p", { class: "lead" }, "What the product should do, by product and feature, and whether the tests show it works."),
    h("div", { class: "cat-summary behaviors-summary" },
      tile(summary.requirement_coverage.text, "requirements with tests", summary.requirements_without_tests.length ? "error" : "passed"),
      tile(summary.automation_coverage.text, "test cases automated", summary.requirements_without_automation.length ? "error" : "passed"),
      tile(n(summary.failing_requirements.length), "failing requirements", summary.failing_requirements.length ? "failed" : "passed"),
      tile(n(summary.uncovered_critical.length), "critical without automated tests", summary.uncovered_critical.length ? "failed" : "passed")),
    h("div", { class: "grid" },
      h("section", { class: "card span-7", "aria-labelledby": "b-tree" },
        h("div", { class: "card-head" }, h("h2", { id: "b-tree" }, "Features"), h("span", { class: "meta" }, `${n(requirements.length)} requirement(s)`)),
        requirements.length ? h("div", { class: "tree behaviors-tree" }, tree) : h("p", { class: "empty" }, "No requirements in the catalog.")),
      h("section", { class: "card span-5", "aria-labelledby": "b-gaps" },
        h("div", { class: "card-head" }, h("h2", { id: "b-gaps" }, "Gaps by owner"), h("span", { class: "meta" }, `${n(gaps.total)} to close, riskiest first`)),
        gaps.owners.length
          ? gaps.owners.map((owner) => h("div", { class: "owner" },
              h("h3", {}, owner.owner, h("span", { class: "sub" }, ` · ${n(owner.gaps.length)}`)),
              h("ol", { class: "rank" }, owner.gaps.map((g) => h("li", {},
                h("span", {}, h("a", { href: `/#/requirement/${encodeURIComponent(g.requirement_id)}` }, g.requirement_id), ` ${g.title}`),
                h("span", { class: "rank-value" }, `${g.kind}${g.criticality ? ` · ${g.criticality}` : ""}`))))))
          : h("p", { class: "empty" }, "Every requirement has automated tests."))),
  ];
}

const tile = (value, label, tone) => h("div", { class: `cat-stat stat-${tone}` }, h("strong", {}, value), h("span", {}, label));
