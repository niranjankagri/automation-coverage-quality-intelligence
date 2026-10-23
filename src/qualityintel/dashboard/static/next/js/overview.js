// Overview: the Allure report's first page for the chosen scope (docs/report-ui.md). Every figure is
// the latest snapshot (latest run of each suite), the same as the classic coverage page.

import { api, scopeQuery } from "./api.js";
import { OUTCOMES, formatDate, h, n, repoName, s, shortDay } from "./dom.js";

export async function overview(state) {
  const d = await api(`/api/report/overview${scopeQuery(state.repository)}`);
  const period = d.first_started_at
    ? `${d.runs} latest run(s), ${formatDate(d.first_started_at)} to ${formatDate(d.latest_started_at)}`
    : "no dated runs";
  return [
    h("div", { class: "report-heading" },
      h("div", { class: "report-heading-copy" },
        h("p", { class: "eyebrow" }, `Report · ${repoName(state.repository)}`),
        h("h1", {}, "Overview"),
        h("p", { class: "lead" }, `The latest result of every suite: ${period}.`)),
      h("div", { class: "report-highlights", role: "group", "aria-label": "Snapshot scope" },
        h("div", { class: "report-highlight" }, h("strong", {}, n(d.suites.length)), h("span", {}, "suite groups")),
        h("div", { class: "report-highlight" }, h("strong", {}, n(d.runs)), h("span", {}, "latest runs")))),
    d.total === 0 ? h("p", { class: "empty" }, "No test results in this scope yet.") : null,
    h(
      "div",
      { class: "grid" },
      summaryCard(d),
      trendCard(d.trend),
      suitesCard(d.suites, state),
      categoriesCard(d.categories),
      environmentCard(d.environment, d.latest_started_at),
    ),
  ];
}

/** The ring with the pass rate in the middle, and the count per status. */
function summaryCard(d) {
  let offset = 0;
  const segments = OUTCOMES.map((outcome) => {
    const share = d.total ? (100 * d.counts[outcome]) / d.total : 0;
    const circle = s("circle", {
      class: `seg-${outcome}`, cx: 60, cy: 60, r: 50, pathLength: 100,
      "stroke-dasharray": `${share} ${100 - share}`, "stroke-dashoffset": -offset,
    });
    offset += share;
    return share ? circle : null;
  });
  const rate = d.pass_rate.percent === null ? "n/a" : `${d.pass_rate.percent.toFixed(d.pass_rate.percent % 1 ? 1 : 0)}%`;
  return h(
    "section",
    { class: "card span-5 summary-card", "aria-labelledby": "summary-title" },
    h("div", { class: "card-head" }, h("h2", { id: "summary-title" }, "Summary"), h("span", { class: "meta" }, `${d.runs} run(s)`)),
    h(
      "div",
      { class: "summary" },
      s("svg", { class: "ring", viewBox: "0 0 120 120", role: "img", "aria-label": `Pass rate ${rate}: ${OUTCOMES.map((o) => `${d.counts[o]} ${o}`).join(", ")}` },
        s("circle", { class: "track", cx: 60, cy: 60, r: 50 }),
        s("g", { transform: "rotate(-90 60 60)" }, segments),
        s("text", { class: "ring-value", x: 60, y: 62, "text-anchor": "middle" }, rate),
        s("text", { class: "ring-label", x: 60, y: 80, "text-anchor": "middle" }, "pass rate"),
      ),
      h(
        "div",
        {},
        h("div", { class: "big-number" }, n(d.total)),
        h("p", { class: "big-label" }, "test results · skipped results are not in the pass rate"),
        h("ul", { class: "legend" }, OUTCOMES.map((o) => h("li", {}, h("span", { class: `dot dot-${o}`, "aria-hidden": "true" }), o, h("span", { class: "num" }, n(d.counts[o]))))),
      ),
    ),
  );
}

/** Stacked bars of each day's snapshot (the latest run of every suite at the end of that day). */
function trendCard(points) {
  const width = 640, height = 190, left = 34, bottom = 22, top = 8;
  const max = Math.max(1, ...points.map((p) => OUTCOMES.reduce((sum, o) => sum + p.counts[o], 0)));
  const band = points.length ? (width - left) / points.length : 0;
  const bar = Math.min(28, band * 0.6);
  const y = (value) => top + (height - top - bottom) * (1 - value / max);
  const bars = points.map((p, i) => {
    let base = 0;
    const x = left + i * band + (band - bar) / 2;
    return s("g", {},
      s("title", {}, `${p.day}: ${OUTCOMES.map((o) => `${p.counts[o]} ${o}`).join(", ")}`),
      OUTCOMES.map((o) => {
        if (!p.counts[o]) return null;
        const rect = s("rect", { class: `fill-${o}`, x, width: bar, y: y(base + p.counts[o]), height: y(base) - y(base + p.counts[o]), rx: 2 });
        base += p.counts[o];
        return rect;
      }),
      i % Math.ceil(points.length / 7) === 0 ? s("text", { class: "axis", x: x + bar / 2, y: height - 6, "text-anchor": "middle" }, shortDay(p.day)) : null,
    );
  });
  return h(
    "section",
    { class: "card span-7 trend-card", "aria-labelledby": "trend-title" },
    h("div", { class: "card-head" }, h("h2", { id: "trend-title" }, "Trend"), h("span", { class: "meta" }, `last ${points.length} day(s) with runs`)),
    points.length
      ? [
          s("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, preserveAspectRatio: "none", "aria-hidden": "true" },
            s("line", { class: "grid-line", x1: left, x2: width, y1: y(max), y2: y(max) }),
            s("text", { class: "axis", x: left - 6, y: y(max) + 4, "text-anchor": "end" }, n(max)),
            s("line", { class: "grid-line", x1: left, x2: width, y1: y(0), y2: y(0) }),
            bars),
          h("details", { class: "numbers" }, h("summary", {}, "Show the numbers"),
            h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Day"), OUTCOMES.map((o) => h("th", { class: "num" }, o)))),
              h("tbody", {}, points.map((p) => h("tr", {}, h("td", {}, p.day), OUTCOMES.map((o) => h("td", { class: "num" }, n(p.counts[o])))))))),
        ]
      : h("p", { class: "empty" }, "No dated runs, so no trend yet."),
  );
}

/** One stacked bar per suite: a repository, or a framework for files that were not collected. */
function suitesCard(suites, state) {
  return h(
    "section",
    { class: "card span-6 suites-card", "aria-labelledby": "suites-title" },
    h("div", { class: "card-head" }, h("h2", { id: "suites-title" }, "Suites"), h("span", { class: "meta" }, `${suites.length} in this scope`)),
    suites.length
      ? h("div", { class: "suite-scroll", role: "region", "aria-label": "Suite results", tabindex: "0" }, h("ul", { class: "suites" }, suites.map((suite) => {
          const total = OUTCOMES.reduce((sum, o) => sum + suite.counts[o], 0);
          const label = suite.collected ? repoName(suite.name) : suite.name;
          const name = suite.collected && !state.repository
            ? h("a", { href: `#/overview?repository=${encodeURIComponent(suite.name)}`, title: `Show only ${suite.name}` }, label)
            : label;
          return h("li", { class: "suite-row" },
            h("div", { class: "suite-top" }, h("span", { class: "suite-name" }, name), h("span", { class: "suite-meta" }, `${n(total)} results · ${suite.runs} run(s)`)),
            h("div", { class: "stack", role: "img", "aria-label": `${label}: ${OUTCOMES.map((o) => `${suite.counts[o]} ${o}`).join(", ")}` },
              OUTCOMES.map((o) => {
                if (!suite.counts[o]) return null;
                const part = h("span", { class: `s-${o}` });
                part.style.width = `${(100 * suite.counts[o]) / total}%`; // CSSOM: allowed by the CSP, inline style= is not
                return part;
              })),
          );
        })))
      : h("p", { class: "empty" }, "No suites in this scope."),
  );
}

/** Failures of the latest results grouped by cause, most affected tests first. */
function categoriesCard(categories) {
  const shown = categories.slice(0, 6);
  return h(
    "section",
    { class: "card span-6 categories-card", "aria-labelledby": "categories-title" },
    h("div", { class: "card-head" }, h("h2", { id: "categories-title" }, "Categories"), h("span", { class: "meta" }, `${categories.length} failure cause(s)`)),
    shown.length
      ? h("ul", { class: "categories" }, shown.map((c) => h("li", { class: "category" },
          h("span", { class: `badge badge-${c.outcome}` }, c.outcome === "error" ? "error" : "failed"),
          h("code", {}, c.signature),
          h("span", { class: "count", title: `${c.tests.length} test(s), ${c.results} result(s)` }, n(c.tests.length)),
        )))
      : h("div", { class: "empty-state" }, h("span", { class: "empty-mark", "aria-hidden": "true" }, "✓"), h("p", {}, "No failures in the latest results.")),
  );
}

/** Where the latest results come from. */
function environmentCard(env, latest) {
  const rows = [
    ["Repositories", env.repositories.length ? env.repositories.map(repoName).join(", ") : "not collected (imported files)"],
    ["Frameworks", env.frameworks.join(", ") || "not recorded"],
    ["Browsers", env.browsers.join(", ") || "not recorded"],
    ["Environments", env.environments.join(", ") || "not recorded"],
    ["Platforms", env.platforms.join(", ") || "not recorded"],
    ["Latest run", formatDate(latest)],
  ];
  return h(
    "section",
    { class: "card span-12 environment-card", "aria-labelledby": "environment-title" },
    h("div", { class: "card-head" }, h("h2", { id: "environment-title" }, "Environment")),
    h("dl", { class: "env" }, rows.map(([k, v]) => [h("dt", {}, k), h("dd", {}, v)])),
  );
}
