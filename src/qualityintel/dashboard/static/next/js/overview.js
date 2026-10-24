// Overview (docs/report-ui.md): four different questions, kept apart. Did the latest tests pass
// (execution pass rate)? Are the requirements automated (coverage, from the catalog)? What critical
// gaps remain? Can it be released (readiness)? Every figure links to the evidence behind it.

import { api, href, query, without } from "./api.js";
import { KIND_LABELS, OUTCOMES, badge, card, clock, contextLine, emptyState, formatDate, h, n, percent, repoName, s, shortDay } from "./dom.js";

// Requirement coverage categories of the feature chart, in reading order
const COVERAGE = [
  ["covered", "Covered and run"], ["not run", "Not run in this scope"], ["not automated", "Not automated"], ["no tests", "No tests"],
];

/** "covered" / "not run" / "not automated" / "no tests" for a requirement in this scope. */
export const coverageOf = (r) =>
  r.coverage_status === "no tests" ? "no tests" : r.coverage_status === "not automated" ? "not automated"
  : r.execution_status === "not run" ? "not run" : "covered";

export async function overview(state, { signal, facts }) {
  const scope = state.scope;
  const q = query(scope);
  const get = (path) => api(path, { signal });
  const [d, summary, readiness, requirements, stability] = await Promise.all([
    get(`/api/report/overview${q}`), get(`/api/summary${q}`), get(`/api/readiness${q}`),
    get(`/api/requirements${q}`), get(`/api/stability${q}`),
  ]);
  const scoped = Object.keys(scope).length > 0;
  const nothing = d.total === 0
    ? emptyState(facts.health?.runs === 0 ? "no-data" : scoped ? "no-match" : "no-data", null,
        scoped ? h("a", { class: "button-quiet", href: href("overview", {}) }, "Show all repositories") : null)
    : null;

  return [
    h("div", { class: "report-heading overview-heading" },
      h("div", {},
        h("p", { class: "eyebrow" }, `Report · ${repoName(scope.repository)}${scope.kind ? ` · ${KIND_LABELS[scope.kind] ?? scope.kind}` : ""}`),
        h("h1", {}, "Overview"),
        h("p", { class: "lead" }, d.first_started_at
          ? `The latest result of every suite in this scope: ${n(d.runs)} run(s), ${formatDate(d.first_started_at)} to ${formatDate(d.latest_started_at)}.`
           : "No dated runs in this scope.")),
      h("div", { class: "hero-actions" },
        h("a", { class: "button", href: href("results", scope) }, "Explore test results", h("span", { "aria-hidden": "true" }, " ↗")),
        h("a", { class: "button-quiet", href: href("coverage", scope) }, "View coverage")),
      h("div", { class: "snapshot-strip", role: "group", "aria-label": "Snapshot scope" },
        h("span", {}, h("strong", {}, n(d.suites.length)), " suite groups"),
        h("span", {}, h("strong", {}, n(d.runs)), " latest runs"),
        h("span", {}, h("strong", {}, n(d.total)), " test results"))),
    nothing,
    headline(d, summary, readiness, scope),
    h("div", { class: "grid" },
      resultsCard(d, scope),
      trendCard(d.trend, scope),
      browsersCard(d.browsers, scope),
      featuresCard(requirements, scope),
      attentionCard(stability, summary, facts.status, scope),
      readinessCard(readiness),
      scopeCard(d, scope)),
  ];
}

/** The four headline figures; each is a link to the evidence behind it. */
function headline(d, summary, readiness, scope) {
  const trend = d.trend;
  const rateOf = (p) => {
    const verdicts = p.counts.passed + p.counts.failed + p.counts.error;
    return verdicts ? (100 * p.counts.passed) / verdicts : null;
  };
  const [before, last] = [trend.at(-2), trend.at(-1)];
  const change = before && last && rateOf(before) !== null && rateOf(last) !== null ? rateOf(last) - rateOf(before) : null;
  const verdicts = d.counts.passed + d.counts.failed + d.counts.error;
  const automation = summary.automation_coverage;
  const tile = (link, tone, label, value, sub, extra = null) =>
    h("a", { class: `kpi kpi-${tone}`, href: link }, h("span", { class: "kpi-label" }, label), h("strong", { class: "kpi-value" }, value), h("span", { class: "kpi-sub" }, sub), extra);
  const READY = { ready: "passed", "at risk": "error", blocked: "failed", unknown: "skipped" };
  return h("div", { class: "kpis", role: "group", "aria-label": "Headline figures" },
    tile(href("results", scope), d.total ? (d.counts.failed + d.counts.error ? "failed" : "passed") : "skipped",
      "Execution pass rate", percent(d.pass_rate),
      d.total ? `${n(d.counts.passed)} of ${n(verdicts)} verdicts passed; ${n(d.counts.skipped)} skipped not counted` : "No results in this scope",
      change !== null && Math.abs(change) >= 0.05
        ? h("span", { class: `kpi-change ${change < 0 ? "down" : "up"}` }, `${change > 0 ? "+" : ""}${change.toFixed(1)} pts vs ${shortDay(before.day)}`)
        : before && last ? h("span", { class: "kpi-change" }, `unchanged vs ${shortDay(before.day)}`) : null),
    tile(href("coverage", scope), automation.denominator ? "accent" : "skipped", "Automation coverage",
      automation.denominator ? `${automation.percent}%` : "Not mapped",
      automation.denominator ? `${n(automation.numerator)} of ${n(automation.denominator)} catalog test cases automated` : "No test cases in the catalog for this scope"),
    tile(href("coverage", scope, { show: "gaps" }), summary.uncovered_critical.length ? "failed" : "passed", "Critical gaps",
      n(summary.uncovered_critical.length), "critical requirements without an automated test"),
    tile(href("overview", scope, { panel: "readiness" }), READY[readiness.state] ?? "skipped", "Release readiness",
      readiness.state === "unknown" ? "Cannot evaluate" : readiness.state[0].toUpperCase() + readiness.state.slice(1), readiness.reasons[0] ?? "no open reasons"));
}

/** The results donut: every segment and legend row opens those results. */
function resultsCard(d, scope) {
  let offset = 0;
  const segments = OUTCOMES.map((outcome) => {
    const share = d.total ? (100 * d.counts[outcome]) / d.total : 0;
    const arc = s("a", { href: href("results", scope, { status: outcome }), "aria-label": `${n(d.counts[outcome])} ${outcome}: show them` },
      s("circle", { class: `seg-${outcome}`, cx: 60, cy: 60, r: 50, pathLength: 100, "stroke-dasharray": `${share} ${100 - share}`, "stroke-dashoffset": -offset }));
    offset += share;
    return share ? arc : null;
  });
  return card("results-title", "Latest results", `${n(d.runs)} run(s)`,
    d.total
      ? h("div", { class: "summary" },
          s("svg", { class: "ring", viewBox: "0 0 120 120", role: "group", "aria-label": `Pass rate ${percent(d.pass_rate)}` },
            s("circle", { class: "track", cx: 60, cy: 60, r: 50 }),
            s("g", { transform: "rotate(-90 60 60)" }, segments),
            s("text", { class: "ring-value", x: 60, y: 62, "text-anchor": "middle" }, percent(d.pass_rate)),
            s("text", { class: "ring-label", x: 60, y: 80, "text-anchor": "middle" }, "pass rate")),
          h("div", {},
            h("div", { class: "big-number" }, n(d.total)),
            h("p", { class: "big-label" }, "latest results · skipped results are not in the pass rate"),
            h("ul", { class: "legend" }, OUTCOMES.map((o) => h("li", {},
              h("a", { href: href("results", scope, { status: o }) }, h("span", { class: `dot dot-${o}`, "aria-hidden": "true" }), o, h("span", { class: "num" }, n(d.counts[o])))))),
            h("p", { class: "pass-rate-text" }, `Pass rate ${d.pass_rate.text}`)))
      : emptyState("no-match"),
    { class: "span-5 accent-indigo" });
}

/** Daily snapshot bars; a day opens that day's results in the same scope. */
// Phones draw on a narrow canvas: a scaled-down desktop chart would be a few pixels tall
const NARROW = window.matchMedia("(max-width: 700px)").matches;

function trendCard(points, scope) {
  const width = NARROW ? 360 : 640, height = 190, left = 34, bottom = 22, top = 8;
  const max = Math.max(1, ...points.map((p) => OUTCOMES.reduce((sum, o) => sum + p.counts[o], 0)));
  const band = points.length ? (width - left) / points.length : 0;
  const bar = Math.min(28, band * 0.6);
  const y = (value) => top + (height - top - bottom) * (1 - value / max);
  const bars = points.map((p, i) => {
    let base = 0;
    const x = left + i * band + (band - bar) / 2;
    const total = OUTCOMES.reduce((sum, o) => sum + p.counts[o], 0);
    return s("a", { href: href("results", { ...scope, since: p.day, until: p.day }), "aria-label": `${shortDay(p.day)}: ${n(total)} results, open them` },
      s("rect", { class: "hit", x: left + i * band, width: band, y: top, height: height - top - bottom }),
      OUTCOMES.map((o) => {
        if (!p.counts[o]) return null;
        const rect = s("rect", { class: `fill-${o}`, x, width: bar, y: y(base + p.counts[o]), height: y(base) - y(base + p.counts[o]), rx: 2 });
        base += p.counts[o];
        return rect;
      }),
      i % Math.ceil(points.length / (NARROW ? 4 : 7)) === 0 ? s("text", { class: "axis", x: x + bar / 2, y: height - 6, "text-anchor": "middle" }, shortDay(p.day)) : null);
  });
  return card("trend-title", "Execution trend", `last ${points.length} day(s) with runs`,
    points.length
      ? [s("svg", { class: "chart", viewBox: `0 0 ${width} ${height}`, role: "group", "aria-label": "Results per day; select a day to open its results" },
          s("line", { class: "grid-line", x1: left, x2: width, y1: y(max), y2: y(max) }),
          s("text", { class: "axis", x: left - 6, y: y(max) + 4, "text-anchor": "end" }, n(max)),
          s("line", { class: "grid-line", x1: left, x2: width, y1: y(0), y2: y(0) }), bars),
        h("details", { class: "numbers" }, h("summary", {}, "Show the numbers"),
          h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Day"), OUTCOMES.map((o) => h("th", { class: "num" }, o)))),
            h("tbody", {}, points.map((p) => h("tr", {}, h("td", {}, h("a", { href: href("results", { ...scope, since: p.day, until: p.day }) }, p.day)),
              OUTCOMES.map((o) => h("td", { class: "num" }, n(p.counts[o]))))))))) ]
      : emptyState("no-match", "No dated runs, so no trend yet."),
    { class: "span-7 accent-cyan" });
}

/** Pass rate, results and recorded time per browser; "No browser" for API and unit runs. */
function browsersCard(browsers, scope) {
  return card("browsers-title", "Browser comparison", `${browsers.length} browser group(s)`,
    browsers.length
      ? [h("div", { class: "browser-cards" }, browsers.map((b) => {
          const bar = h("span", { class: "browser-progress-fill" });
          bar.style.width = `${b.pass_rate.percent ?? 0}%`;
          const content = [
            h("span", { class: "browser-card-top" }, h("strong", {}, b.browser ?? "No browser"), h("span", { class: "browser-rate" }, percent(b.pass_rate))),
            h("span", { class: "browser-progress", "aria-hidden": "true" }, bar),
            h("span", { class: "browser-card-meta" }, `${n(b.total)} results`, h("span", {}, b.duration_seconds === null ? "time not recorded" : clock(b.duration_seconds))),
            b.untimed ? h("small", { class: "sub" }, `${n(b.untimed)} without recorded duration`) : null,
          ];
          return b.browser
            ? h("a", { class: "browser-card", href: href("results", { ...without(scope, "browser"), browser: b.browser }), "aria-label": `${b.browser}: ${n(b.total)} results, ${percent(b.pass_rate)} pass rate` }, content)
            : h("div", { class: "browser-card" }, content);
        })),
        h("details", { class: "numbers" }, h("summary", {}, "Compare exact numbers"),
        h("div", { class: "table-wrap" }, h("table", { class: "compare" },
          h("thead", {}, h("tr", {}, h("th", {}, "Browser"), h("th", { class: "num" }, "Results"), h("th", {}, "Pass rate"), h("th", { class: "num" }, "Recorded time"))),
          h("tbody", {}, browsers.map((b) => {
            const bar = h("span", { class: "meter-fill" });
            bar.style.width = `${b.pass_rate.percent ?? 0}%`;
            return h("tr", {},
              h("td", {}, b.browser ? h("a", { href: href("results", { ...without(scope, "browser"), browser: b.browser }) }, b.browser) : h("span", { title: "API, unit and other runs without a browser" }, "No browser")),
              h("td", { class: "num" }, n(b.total)),
              h("td", {}, h("span", { class: "meter" }, bar), " ", percent(b.pass_rate)),
              h("td", { class: "num" }, b.duration_seconds === null ? "not recorded" : clock(b.duration_seconds), b.untimed && b.duration_seconds !== null ? h("small", { class: "sub" }, ` (${n(b.untimed)} untimed)`) : null));
          })))))]
      : emptyState("no-match"),
    { class: "span-6 accent-purple" });
}

/** Requirements per product: covered and run, not run here, not automated, no tests. */
function featuresCard(requirements, scope) {
  const products = new Map();
  for (const r of requirements) {
    const product = (r.feature || "Unassigned").split(" / ")[0];
    const counts = products.get(product) ?? Object.fromEntries(COVERAGE.map(([key]) => [key, 0]));
    counts[coverageOf(r)] += 1;
    products.set(product, counts);
  }
  const rows = [...products.entries()].sort(([a], [b]) => a.localeCompare(b));
  return card("features-title", "Feature coverage", `${n(requirements.length)} requirement(s), sample catalog`,
    rows.length
      ? [h("ul", { class: "feature-bars" }, rows.map(([product, counts]) => {
          const total = COVERAGE.reduce((sum, [key]) => sum + counts[key], 0);
          return h("li", {},
            h("a", { class: "feature-name", href: href("coverage", scope, { product }) }, product, h("small", {}, ` ${n(total)}`)),
            h("span", { class: "stack", role: "img", "aria-label": COVERAGE.map(([key, label]) => `${counts[key]} ${label}`).join(", ") },
              COVERAGE.map(([key]) => {
                if (!counts[key]) return null;
                const part = h("span", { class: `cov-${key.replace(" ", "-")}`, title: `${counts[key]} ${key}` });
                part.style.width = `${(100 * counts[key]) / total}%`;
                return part;
              })));
        })),
        h("ul", { class: "legend legend-inline" }, COVERAGE.map(([key, label]) => h("li", {}, h("span", { class: `dot cov-${key.replace(" ", "-")}`, "aria-hidden": "true" }), label)))]
      : emptyState("not-mapped", "No requirements in the catalog."),
    { class: "span-6 accent-cyan" });
}

/** What to look at first: new failures, critical gaps, slower tests, data problems. */
function attentionCard(stability, summary, status, scope) {
  const failing = stability.rows.filter((r) => r.status === "new failure" || r.status === "consistently failing").length;
  const flaky = stability.rows.filter((r) => r.status === "flaky candidate").length;
  const items = [
    [failing, "failed", `${n(failing)} new or consistently failing test(s)`, href("failures", scope)],
    [flaky, "error", `${n(flaky)} flaky candidate(s)`, href("failures", scope)],
    [summary.uncovered_critical.length, "failed", `${n(summary.uncovered_critical.length)} critical requirement(s) without automated tests`, href("coverage", scope, { show: "gaps" })],
    [stability.duration_regressions.length, "error", `${n(stability.duration_regressions.length)} test(s) markedly slower`, href("trends", scope)],
    [status?.incomplete_collections_7d ?? 0, "error", `${n(status?.incomplete_collections_7d ?? 0)} incomplete collection(s) in 7 days`, "/#/collection"],
    [status?.stale ? 1 : 0, "failed", "The data could not be reloaded; figures may be old", "/#/collection"],
  ].filter(([count]) => count);
  return card("attention-title", "Needs attention", items.length ? `${items.length} item(s)` : "all clear",
    items.length
      ? h("ul", { class: "attention" }, items.map(([, tone, text, link]) => h("li", {}, h("span", { class: `dot dot-${tone}`, "aria-hidden": "true" }), h("a", { href: link }, text))))
      : emptyState("clear"),
    { class: "span-5 accent-amber" });
}

/** Why the release decision is what it is (or why it cannot be made). */
function readinessCard(readiness) {
  const TONE = { pass: "passed", fail: "failed", warning: "error", unknown: "skipped" };
  return card("readiness-title", "Release readiness", readiness.gate_name ? `gate: ${readiness.gate_name}` : "no gate configured",
    [h("p", { class: "readiness-state" }, badge(TONE[readiness.state === "ready" ? "pass" : readiness.state === "blocked" ? "fail" : readiness.state === "at risk" ? "warning" : "unknown"], readiness.state === "unknown" ? "cannot be evaluated" : readiness.state)),
      readiness.reasons.length ? h("ul", { class: "reasons" }, readiness.reasons.map((r) => h("li", {}, r))) : h("p", { class: "sub" }, "Every measured rule passes."),
      h("details", { class: "numbers" }, h("summary", {}, `Scorecard (${readiness.scorecard.length} checks)`),
        h("div", { class: "table-wrap" }, h("table", {},
          h("thead", {}, h("tr", {}, h("th", {}, "Check"), h("th", {}, "Measured"), h("th", {}, "Threshold"), h("th", {}, "Result"))),
          h("tbody", {}, readiness.scorecard.map((c) => h("tr", {},
            h("td", {}, c.name, h("small", { class: "sub block" }, c.explanation)), h("td", {}, c.measured), h("td", {}, c.threshold),
            h("td", {}, badge(TONE[c.result] ?? "skipped", c.result))))))))],
    { class: "span-7 accent-indigo", id: "readiness" });
}

/** What the figures are about: repositories with their latest branch, commit and CI run. */
function scopeCard(d, scope) {
  const env = d.environment;
  return card("scope-title", "Selected scope", `${n(d.suites.length)} group(s)`,
    [d.suites.length
      ? h("ul", { class: "suites" }, d.suites.map((suite) => {
          const total = OUTCOMES.reduce((sum, o) => sum + suite.counts[o], 0);
          const name = suite.collected && !scope.repository
            ? h("a", { href: href("overview", { ...scope, repository: suite.name }), title: suite.name }, repoName(suite.name))
            : h("span", { title: suite.name }, suite.collected ? repoName(suite.name) : suite.name);
          const stack = h("span", { class: "stack", "aria-hidden": "true" }, OUTCOMES.map((o) => {
            if (!suite.counts[o]) return null;
            const part = h("span", { class: `s-${o}` });
            part.style.width = `${(100 * suite.counts[o]) / total}%`;
            return part;
          }));
          return h("li", { class: "suite-row" },
            h("div", { class: "suite-top" }, h("span", { class: "suite-name" }, name),
              h("span", { class: "suite-meta" }, contextLine([`${n(total)} results`, `${n(suite.runs)} run(s)`,
                suite.branch, suite.commit ? `commit ${suite.commit.slice(0, 7)}` : null]),
                suite.ci_url ? [" · ", h("a", { href: suite.ci_url, rel: "noopener noreferrer", target: "_blank" }, "CI run")] : null)),
            stack);
        }))
      : emptyState("no-match"),
      h("dl", { class: "env" },
        [["Frameworks", env.frameworks], ["Browsers", env.browsers], ["Environments", env.environments], ["Platforms", env.platforms]]
          .map(([label, values]) => [h("dt", {}, label), h("dd", {}, values.length ? values.join(", ") : "not recorded")]),
        h("dt", {}, "Latest run"), h("dd", {}, formatDate(d.latest_started_at)))],
    { class: "span-12 accent-purple" });
}
