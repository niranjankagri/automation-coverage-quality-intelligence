// Trends (docs/report-ui.md): results and pass rate per day, suite time per day, how long the latest
// tests take and which are slowest (by job and browser: the same test is slow per context), what got
// slower, and the release gate per day. A day opens its results; every chart has its numbers.

import { api, href, query } from "./api.js";
import { OUTCOMES, card, clock, emptyState, h, loadMore, n, repoName, s, shortDay } from "./dom.js";
import { ranIn, testLink } from "./results.js";
import { shortKey } from "./failures.js";

const DAYS = 30;
const BUCKETS = [[0.1, "< 0.1 s"], [1, "0.1–1 s"], [5, "1–5 s"], [30, "5–30 s"], [Infinity, "≥ 30 s"]];
// Drawing size; a full-width card gets a wider canvas so the chart fills it at the same height. A phone
// gets a narrow canvas: scaled-down desktop charts would be a few pixels tall with unreadable labels.
const NARROW = window.matchMedia("(max-width: 700px)").matches;
const W = NARROW ? 360 : 640, WIDE = NARROW ? 360 : 1240, H = 190, LEFT = 48, BOTTOM = 22, TOP = 10;
// A day whose results recorded no duration has an unknown time, not zero (DailyView.timed_results)
const timeOf = (d) => (d.timed_results ? d.duration_seconds : null);
const axisClock = (value) => (value >= 60 ? `${Math.round(value / 60)} min` : clock(value));

export async function trends(state, { signal }) {
  const scope = state.scope;
  const q = query(scope);
  const [history, tree, stability, gate] = await Promise.all([
    api(`/api/trends${q}`, { signal }), api(`/api/report/suites${q}`, { signal }),
    api(`/api/stability${q}`, { signal }), api(`/api/gate-history${q}`, { signal }),
  ]);
  const daily = history.daily.slice(-DAYS);
  const dayHref = (day) => href("results", { ...scope, since: day, until: day });
  const rows = tree.groups.flatMap((group) => group.jobs.flatMap((job) => job.classes.flatMap((cls) => cls.tests.map((test) => ({ test, job, group })))));
  const timed = rows.filter((r) => r.test.duration_seconds !== null).sort((a, b) => b.test.duration_seconds - a.test.duration_seconds);

  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(scope.repository)}`),
    h("h1", {}, "Trends"),
    h("p", { class: "lead" }, `How the results and their timing change over the last ${n(daily.length)} day(s) with runs. Select a day to open its results.`),
    h("div", { class: "grid" },
      card("t-results", "Results per day", `${n(daily.length)} day(s) with runs`, daily.length
        ? [stackedBars(daily, dayHref), table(["Day", ...OUTCOMES], daily.map((d) => [h("a", { href: dayHref(d.day) }, d.day), ...OUTCOMES.map((o) => n(d.counts[o]))]))]
        : emptyState("no-match", "No dated runs, so no history yet."), { class: "span-12 accent-indigo" }),
      card("t-rate", "Pass rate per day", "skipped results not counted", daily.length
        ? [line(daily.map((d) => ({ day: d.day, value: d.pass_rate.percent })), dayHref), table(["Day", "Pass rate"], daily.map((d) => [d.day, d.pass_rate.text]))]
        : emptyState("no-match"), { class: "span-6 accent-cyan" }),
      card("t-time", "Suite time per day", "sum of recorded test durations", daily.length
        ? [bars(daily, dayHref), table(["Day", "Test time"], daily.map((d) => [d.day, clock(timeOf(d))]))]
        : emptyState("no-match"), { class: "span-6 accent-cyan" }),
      card("t-spread", "How long tests take now", `${n(rows.length)} latest results`, rows.length ? distribution(rows) : emptyState("no-match"), { class: "span-6 accent-purple" }),
      card("t-slowest", "Slowest tests now", "per job and browser", timed.length
        ? loadMore(timed, ({ test, job, group }) => h("li", {},
            h("a", { href: testLink(test, group, job) }, test.name, h("small", { class: "sub block" }, ranIn(group, job))),
            h("span", { class: "rank-value" }, clock(test.duration_seconds))), { step: 10, label: "timed tests", list: "ol", listClass: "rank" })
        : emptyState("none", "No durations recorded."), { class: "span-6 accent-purple" }),
      card("t-slower", "Getting slower", "latest run against the usual time of the same test and context", stability.duration_regressions.length
        ? table(["Test", "Context", "Usual", "Latest", "Change"], stability.duration_regressions.map((r) => [
            h("a", { href: href("test", scope, { key: r.key }) }, shortKey(r.key)), r.context, clock(r.baseline_seconds), clock(r.latest_seconds),
            `× ${(r.latest_seconds / r.baseline_seconds).toFixed(1)}`]), true)
        : emptyState("none", "No test got markedly slower."), { class: "span-12 accent-amber" }),
      card("t-gate", `Release gate per day${gate.gate_name ? `: ${gate.gate_name}` : ""}`, `${n(gate.days.length)} day(s)`, gate.days.length
        ? [h("ol", { class: "gate-days", "aria-label": "Gate result per day, oldest first" }, gate.days.map((d) => h("li", { class: `gate-day gate-${tone(d.status)}`, title: `${d.day}: ${d.status}${d.failed_rules.length ? ` (${d.failed_rules.join(", ")})` : ""}` }, h("span", {}, shortDay(d.day)), h("strong", {}, d.status)))),
           gate.changes.length
             ? table(["Day", "From", "To", "Started failing", "Stopped failing"], gate.changes.map((c) => [c.day, c.previous, c.status, c.started_failing.join(", ") || "–", c.stopped_failing.join(", ") || "–"]), true)
             : h("p", { class: "sub" }, "The gate result did not change in this period.")]
        : emptyState("none", `Cannot be evaluated: ${gate.notes.join(" ") || "no gate history."}`), { class: "span-12 accent-indigo" })),
  ];
}

const tone = (status) => (/fail|block/i.test(status) ? "failed" : /pass|ready/i.test(status) ? "passed" : "skipped");

/** The numbers behind a chart; open when the table is the content itself. */
function table(head, rows, open = false) {
  const body = h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, head.map((cell, i) => h("th", { class: i ? "num" : null }, cell)))),
    h("tbody", {}, rows.map((row) => h("tr", {}, row.map((cell, i) => h("td", { class: i ? "num" : null }, cell)))))));
  return open ? body : h("details", { class: "numbers" }, h("summary", {}, "Show the numbers"), body);
}

const yScale = (max, min = 0) => (value) => TOP + (H - TOP - BOTTOM) * (1 - (value - min) / Math.max(1e-9, max - min));
const every = (count) => Math.max(1, Math.ceil(count / (NARROW ? 4 : 8)));
const frame = (y, max, min, format, w) => [
  s("line", { class: "grid-line", x1: LEFT, x2: w, y1: y(max), y2: y(max) }),
  s("text", { class: "axis", x: LEFT - 6, y: y(max) + 4, "text-anchor": "end" }, format(max)),
  s("line", { class: "grid-line", x1: LEFT, x2: w, y1: y(min), y2: y(min) }),
  s("text", { class: "axis", x: LEFT - 6, y: y(min) + 4, "text-anchor": "end" }, format(min)),
];
const svg = (w, label, ...children) => s("svg", { class: "chart", viewBox: `0 0 ${w} ${H}`, role: "group", "aria-label": label }, children);
const dayLabel = (x, text, w) => s("text", { class: "axis", x, y: H - 6, "text-anchor": x > w - 30 ? "end" : "middle" }, text);
/** A day's chart marks, as a link to that day's results. */
const dayLink = (day, label, link, children) => s("a", { href: link(day), "aria-label": `${shortDay(day)}: ${label}, open the results` }, children);

function stackedBars(days, link) {
  const max = Math.max(1, ...days.map((d) => OUTCOMES.reduce((sum, o) => sum + d.counts[o], 0)));
  const y = yScale(max);
  const band = (WIDE - LEFT) / days.length, bar = Math.min(26, band * 0.65);
  return svg(WIDE, "Results per day; select a day to open its results", frame(y, max, 0, n, WIDE), days.map((d, i) => {
    let base = 0;
    const x = LEFT + i * band + (band - bar) / 2;
    const total = OUTCOMES.reduce((sum, o) => sum + d.counts[o], 0);
    return [dayLink(d.day, `${n(total)} results`, link, [
      s("rect", { class: "hit", x: LEFT + i * band, width: band, y: TOP, height: H - TOP - BOTTOM }),
      OUTCOMES.map((o) => {
        if (!d.counts[o]) return null;
        const rect = s("rect", { class: `fill-${o}`, x, width: bar, y: y(base + d.counts[o]), height: y(base) - y(base + d.counts[o]), rx: 2 });
        base += d.counts[o];
        return rect;
      })]),
      i % every(days.length) === 0 ? dayLabel(x + bar / 2, shortDay(d.day), WIDE) : null];
  }));
}

/** Suite time per day; a day without recorded durations has no bar and says so (not zero). */
function bars(days, link) {
  const values = days.map(timeOf);
  const max = Math.max(1e-9, ...values.filter((v) => v !== null));
  const y = yScale(max);
  const band = (W - LEFT) / days.length, bar = Math.min(26, band * 0.65);
  return svg(W, "Recorded test time per day", frame(y, max, 0, axisClock, W), days.map((d, i) => {
    const x = LEFT + i * band + (band - bar) / 2;
    const time = timeOf(d);
    return [dayLink(d.day, time === null ? "time not recorded" : clock(time), link, [
      s("rect", { class: "hit", x: LEFT + i * band, width: band, y: TOP, height: H - TOP - BOTTOM }),
      time === null
        ? s("text", { class: "axis not-recorded", x: x + bar / 2, y: y(0) - 4, "text-anchor": "middle" }, "–")
        : s("rect", { class: "fill-accent", x, width: bar, y: y(time), height: y(0) - y(time), rx: 2 })]),
      i % every(days.length) === 0 ? dayLabel(x + bar / 2, shortDay(d.day), W) : null];
  }));
}

/** The pass rate as a line; the axis starts below the lowest day so dips stay visible (labelled). */
function line(points, link) {
  const known = points.filter((p) => p.value !== null);
  if (!known.length) return emptyState("no-match", "No verdicts on these days (only skipped results), so no pass rate.");
  const low = Math.min(...known.map((p) => p.value));
  const min = Math.max(0, Math.floor((low - 5) / 10) * 10), max = 100;
  const y = yScale(max, min);
  const step = points.length > 1 ? (W - LEFT - 16) / (points.length - 1) : 0;
  const xs = points.map((_, i) => LEFT + 8 + i * step);
  const path = points.map((p, i) => (p.value === null ? null : `${xs[i]},${y(p.value)}`)).filter(Boolean).join(" ");
  return svg(W, "Pass rate per day", frame(y, max, min, (v) => `${v}%`, W),
    s("polyline", { class: "line-accent", points: path }),
    points.map((p, i) => [p.value === null ? null : dayLink(p.day, `${p.value}% passed`, link, [s("circle", { class: "dot-accent", cx: xs[i], cy: y(p.value), r: 4 })]),
      i % every(points.length) === 0 ? dayLabel(xs[i], shortDay(p.day), W) : null]));
}

/** Latest results per duration bucket; results without a duration are counted apart, not as fast. */
function distribution(rows) {
  const counts = BUCKETS.map(() => 0);
  let unknown = 0;
  for (const { test } of rows) {
    if (test.duration_seconds === null) unknown += 1;
    else counts[BUCKETS.findIndex(([upper]) => test.duration_seconds < upper)] += 1;
  }
  const max = Math.max(1, ...counts);
  return [
    h("ul", { class: "spread" }, BUCKETS.map(([, label], i) => {
      const fill = h("span", { class: "spread-fill" });
      fill.style.width = `${(counts[i] / max) * 100}%`;
      return h("li", {}, h("span", { class: "spread-label" }, label), h("span", { class: "spread-bar" }, fill), h("span", { class: "spread-count" }, n(counts[i])));
    })),
    unknown ? h("p", { class: "sub" }, `${n(unknown)} result(s) without a recorded duration are not in these buckets.`) : null,
  ];
}
