// Graphs: Allure's graphs page (docs/report-ui.md) on the history the API already keeps: results and
// pass rate per day, suite time per day, how long tests take now, what got slower, and the release
// gate per day. Every chart has its numbers in a table below it.

import { api, scopeQuery } from "./api.js";
import { OUTCOMES, h, n, repoName, s, shortDay } from "./dom.js";

// Days on the daily charts (the newest days with runs)
const DAYS = 30;
// Slowest tests listed
const SLOWEST = 10;
// Duration buckets: [upper bound in seconds, label]
const BUCKETS = [[0.1, "< 0.1 s"], [1, "0.1–1 s"], [5, "1–5 s"], [30, "5–30 s"], [Infinity, "≥ 30 s"]];

// Drawing size; a full-width card gets a wider canvas so the chart fills it at the same height. A phone
// gets a narrow canvas: scaled-down desktop charts would be a few pixels tall with unreadable labels.
const NARROW = window.matchMedia("(max-width: 700px)").matches;
const W = NARROW ? 360 : 640, WIDE = NARROW ? 360 : 1240, H = 190, LEFT = 48, BOTTOM = 22, TOP = 10;

const clock = (value) => (value === null || value === undefined ? "–" : value < 1 ? `${Math.round(value * 1000)} ms`
  : value < 120 ? `${value.toFixed(value < 10 ? 2 : 1)} s` : `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`);

export async function graphs(state) {
  const scope = scopeQuery(state.repository);
  const [trends, tree, stability, gate] = await Promise.all([
    api(`/api/trends${scope}`),
    api(`/api/report/suites${scope}`),
    api(`/api/stability${scope}`),
    api(`/api/gate-history${scope}`),
  ]);
  const daily = trends.daily.slice(-DAYS);
  const tests = tree.groups.flatMap((g) => g.jobs.flatMap((j) => j.classes.flatMap((c) => c.tests)));
  const suiteLink = (key) => `#/suites${scopeQuery(state.repository, { test: key })}`;

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(state.repository)}`),
    h("h1", {}, "Graphs"),
    h("p", { class: "lead" }, `How the results and their timing change over the last ${n(daily.length)} day(s) with runs.`),
    h("div", { class: "grid" },
      card("span-12", "g-results", "Results per day", `${n(daily.length)} day(s) with runs`, daily.length
        ? [stackedBars(daily, WIDE), table(["Day", ...OUTCOMES], daily.map((d) => [d.day, ...OUTCOMES.map((o) => n(d.counts[o]))]))]
        : empty("No dated runs, so no history yet.")),
      card("span-6", "g-rate", "Pass rate per day", "skipped results not counted", daily.length
        ? [line(daily.map((d) => ({ day: d.day, value: d.pass_rate.percent }))),
           table(["Day", "Pass rate"], daily.map((d) => [d.day, d.pass_rate.text]))]
        : empty("No dated runs.")),
      card("span-6", "g-time", "Suite time per day", "sum of test durations in the day's snapshot", daily.length
        ? [bars(daily.map((d) => ({ label: shortDay(d.day), title: `${d.day}: ${clock(d.duration_seconds)}`, value: d.duration_seconds ?? 0 })), axisClock),
           table(["Day", "Test time"], daily.map((d) => [d.day, clock(d.duration_seconds)]))]
        : empty("No dated runs.")),
      card("span-6", "g-spread", "How long tests take now", `${n(tests.length)} latest results`, tests.length
        ? distribution(tests)
        : empty("No results in this scope.")),
      card("span-6", "g-slowest", "Slowest tests now", `top ${SLOWEST}`, tests.some((t) => t.duration_seconds)
        ? h("ol", { class: "rank" }, [...tests].filter((t) => t.duration_seconds).sort((a, b) => b.duration_seconds - a.duration_seconds).slice(0, SLOWEST)
            .map((t) => h("li", {}, h("a", { href: suiteLink(t.key) }, t.name), h("span", { class: "rank-value" }, clock(t.duration_seconds)))))
        : empty("No durations recorded.")),
      card("span-12", "g-slower", "Getting slower", "latest run against the usual time of the same test and context", stability.duration_regressions.length
        ? table(["Test", "Context", "Usual", "Latest", "Change"], stability.duration_regressions.map((r) => [
            h("a", { href: suiteLink(r.key) }, r.key.split("::").at(-1)), r.context, clock(r.baseline_seconds), clock(r.latest_seconds),
            `× ${(r.latest_seconds / r.baseline_seconds).toFixed(1)}`]), true)
        : empty("No test got markedly slower.")),
      card("span-12", "g-gate", `Release gate per day${gate.gate_name ? `: ${gate.gate_name}` : ""}`, `${n(gate.days.length)} day(s)`, gate.days.length
        ? [h("ol", { class: "gate-days", "aria-label": "Gate result per day, oldest first" }, gate.days.map((d) => h("li", { class: `gate-day gate-${tone(d.status)}`, title: `${d.day}: ${d.status}${d.failed_rules.length ? ` (${d.failed_rules.join(", ")})` : ""}` }, h("span", {}, shortDay(d.day)), h("strong", {}, d.status)))),
           gate.changes.length
             ? table(["Day", "From", "To", "Started failing", "Stopped failing"], gate.changes.map((c) => [c.day, c.previous, c.status, c.started_failing.join(", ") || "–", c.stopped_failing.join(", ") || "–"]), true)
             : h("p", { class: "sub" }, "The gate result did not change in this period.")]
        : empty(gate.notes.join(" ") || "No gate history.")),
    ),
  ];
}

// Axis labels stay short: "2 min" rather than "1 min 53 s"
const axisClock = (value) => (value >= 60 ? `${Math.round(value / 60)} min` : clock(value));
const tone = (status) => (/fail|block/i.test(status) ? "failed" : /pass|ready/i.test(status) ? "passed" : "skipped");
const empty = (text) => h("p", { class: "empty" }, text);

function card(span, id, title, meta, body) {
  return h("section", { class: `card ${span}`, "aria-labelledby": id },
    h("div", { class: "card-head" }, h("h2", { id }, title), h("span", { class: "meta" }, meta)), body);
}

/** The numbers behind a chart; open by default when the table is the content itself. */
function table(head, rows, open = false) {
  const body = h("table", {}, h("thead", {}, h("tr", {}, head.map((cell, i) => h("th", { class: i ? "num" : null }, cell)))),
    h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell, i) => h("td", { class: i ? "num" : null }, cell))))));
  return open ? h("div", { class: "table-wrap" }, body) : h("details", { class: "numbers" }, h("summary", {}, "Show the numbers"), body);
}

const yScale = (max, min = 0) => (value) => TOP + (H - TOP - BOTTOM) * (1 - (value - min) / Math.max(1e-9, max - min));
const every = (count) => Math.max(1, Math.ceil(count / (NARROW ? 4 : 8)));
const frame = (y, max, min, format, w = W) => [
  s("line", { class: "grid-line", x1: LEFT, x2: w, y1: y(max), y2: y(max) }),
  s("text", { class: "axis", x: LEFT - 6, y: y(max) + 4, "text-anchor": "end" }, format(max)),
  s("line", { class: "grid-line", x1: LEFT, x2: w, y1: y(min), y2: y(min) }),
  s("text", { class: "axis", x: LEFT - 6, y: y(min) + 4, "text-anchor": "end" }, format(min)),
];
const svg = (w, ...children) => s("svg", { class: "chart", viewBox: `0 0 ${w} ${H}`, "aria-hidden": "true" }, children);
// A day label under x; the last ones anchor to their end so they are not cut off at the edge
const dayLabel = (x, text, w) => s("text", { class: "axis", x, y: H - 6, "text-anchor": x > w - 30 ? "end" : "middle" }, text);

/** One stacked bar per day, a segment per outcome. */
function stackedBars(days, w = W) {
  const max = Math.max(1, ...days.map((d) => OUTCOMES.reduce((sum, o) => sum + d.counts[o], 0)));
  const y = yScale(max);
  const band = (w - LEFT) / days.length, bar = Math.min(26, band * 0.65);
  return svg(w, frame(y, max, 0, n, w), days.map((d, i) => {
    let base = 0;
    const x = LEFT + i * band + (band - bar) / 2;
    return s("g", {}, s("title", {}, `${d.day}: ${OUTCOMES.map((o) => `${d.counts[o]} ${o}`).join(", ")}`),
      OUTCOMES.map((o) => {
        if (!d.counts[o]) return null;
        const rect = s("rect", { class: `fill-${o}`, x, width: bar, y: y(base + d.counts[o]), height: y(base) - y(base + d.counts[o]), rx: 2 });
        base += d.counts[o];
        return rect;
      }),
      i % every(days.length) === 0 ? dayLabel(x + bar / 2, shortDay(d.day), w) : null);
  }));
}

/** Single-series bars (accent colour). */
function bars(points, format) {
  const max = Math.max(1e-9, ...points.map((p) => p.value));
  const y = yScale(max);
  const band = (W - LEFT) / points.length, bar = Math.min(26, band * 0.65);
  return svg(W, frame(y, max, 0, format), points.map((p, i) => {
    const x = LEFT + i * band + (band - bar) / 2;
    return s("g", {}, s("title", {}, p.title),
      s("rect", { class: "fill-accent", x, width: bar, y: y(p.value), height: y(0) - y(p.value), rx: 2 }),
      i % every(points.length) === 0 ? dayLabel(x + bar / 2, p.label, W) : null);
  }));
}

/** The pass rate as a line; the axis starts below the lowest day so dips stay visible (labelled). */
function line(points) {
  const low = Math.min(...points.map((p) => p.value ?? 100));
  const min = Math.max(0, Math.floor((low - 5) / 10) * 10), max = 100;
  const y = yScale(max, min);
  const step = points.length > 1 ? (W - LEFT - 16) / (points.length - 1) : 0;
  const xy = points.map((p, i) => [LEFT + 8 + i * step, y(p.value ?? min)]);
  return svg(W, frame(y, max, min, (v) => `${v}%`),
    s("polyline", { class: "line-accent", points: xy.map(([x, yy]) => `${x},${yy}`).join(" ") }),
    xy.map(([x, yy], i) => s("g", {}, s("title", {}, `${points[i].day}: ${points[i].value ?? "–"}%`), s("circle", { class: "dot-accent", cx: x, cy: yy, r: 3.5 }),
      i % every(points.length) === 0 ? dayLabel(x, shortDay(points[i].day), W) : null)));
}

/** Latest results per duration bucket, as horizontal bars with counts. */
function distribution(tests) {
  const counts = BUCKETS.map(() => 0);
  let unknown = 0;
  for (const t of tests) {
    if (t.duration_seconds === null || t.duration_seconds === undefined) unknown += 1;
    else counts[BUCKETS.findIndex(([upper]) => t.duration_seconds < upper)] += 1;
  }
  const max = Math.max(1, ...counts);
  return [
    h("ul", { class: "spread" }, BUCKETS.map(([, label], i) => {
      const fill = h("span", { class: "spread-fill" });
      fill.style.width = `${(counts[i] / max) * 100}%`;
      return h("li", {}, h("span", { class: "spread-label" }, label), h("span", { class: "spread-bar" }, fill), h("span", { class: "spread-count" }, n(counts[i])));
    })),
    unknown ? h("p", { class: "sub" }, `${n(unknown)} result(s) without a recorded duration.`) : null,
  ];
}

