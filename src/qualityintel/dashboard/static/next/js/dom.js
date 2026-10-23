// DOM helpers for the report. Every value is written as text (never as HTML), so imported test names
// and failure messages cannot inject markup.

export const OUTCOMES = ["passed", "failed", "error", "skipped"];

// Execution families (traceability/report.py, EXECUTION_KINDS) as the filter bar names them
export const KIND_LABELS = {
  api: "API", unit: "Unit", component: "Component", integration: "Integration", contract: "Contract",
  ui: "UI", visual: "Visual", accessibility: "Accessibility", mobile: "Mobile", performance: "Performance",
  other: "Other (job name not recognised)",
};

/** An element with attributes and children; arrays of children are flattened at any depth. */
export function h(tag, attrs = {}, ...children) {
  return build(document.createElement(tag), attrs, children);
}

/** An SVG element (charts). */
export function s(tag, attrs = {}, ...children) {
  return build(document.createElementNS("http://www.w3.org/2000/svg", tag), attrs, children);
}

function build(el, attrs, children) {
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "class") el.setAttribute("class", value);
    else el.setAttribute(name, value === true ? "" : String(value));
  }
  for (const child of children.flat(Infinity)) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Content parts without the optional ones left out (null/undefined), for replaceChildren. */
export const present = (parts) => [parts].flat(Infinity).filter((part) => part !== null && part !== undefined && part !== false);

/** "19 Oct 2026, 10:33 UTC" for an ISO timestamp; "not recorded" without one. */
export function formatDate(iso, withTime = true) {
  if (!iso) return "not recorded";
  const date = new Date(iso);
  const day = date.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
  if (!withTime) return day;
  const time = date.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
  return `${day}, ${time} UTC`;
}

/** "19 Oct" for an ISO date (chart axes). */
export const shortDay = (iso) =>
  new Date(`${iso.slice(0, 10)}T00:00:00Z`).toLocaleDateString("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

/** Thousands separators for counts. */
export const n = (value) => Number(value).toLocaleString("en-GB");

/** "niranjankagri/cypress-typescript-framework" -> "cypress-typescript-framework". */
export const repoName = (value) => (value ? value.split("/").at(-1) : "All repositories");

/** A duration; a missing one is "not recorded", never zero. */
export const clock = (value) => (value === null || value === undefined ? "not recorded"
  : value < 1 ? `${Math.round(value * 1000)} ms`
  : value < 120 ? `${value.toFixed(value < 10 ? 2 : 1)} s`
  : `${Math.floor(value / 60)} min ${Math.round(value % 60)} s`);

/** "93.5%" or "No results" (never 100% of nothing). */
export const percent = (ratio) => (ratio.percent === null || ratio.percent === undefined ? "No results"
  : `${ratio.percent.toFixed(ratio.percent % 1 ? 1 : 0)}%`);

/** "ui-firefox · firefox · ci · linux" for a context; parts that are missing are left out. */
export const contextLine = (parts) => parts.filter(Boolean).join(" · ");

/** A status badge. */
export const badge = (outcome, text = outcome) => h("span", { class: `badge badge-${outcome}` }, text);

/** A card with a heading, an optional note on the right, and its body. */
export function card(id, title, meta, body, attrs = {}) {
  return h("section", { ...attrs, class: `card ${attrs.class ?? ""}`.trim(), "aria-labelledby": id },
    h("div", { class: "card-head" }, h("h2", { id }, title), meta ? h("span", { class: "meta" }, meta) : null),
    body);
}

/**
 * What an empty area means, never just "nothing": no data collected at all, nothing matching the
 * filters, a combination that does not exist, or evidence that cannot be calculated.
 */
export function emptyState(kind, detail = null, action = null) {
  const TEXT = {
    "no-data": ["No collected data yet", "The dashboard has no test results; collection has not run or found nothing."],
    "no-match": ["No results match these filters", "The collected data has results, but none in this scope."],
    unsupported: ["This filter combination does not exist", "No collected run has this combination; widen a filter."],
    "not-mapped": ["Coverage not mapped", "None of the results in this scope link to a requirement, so coverage cannot be calculated."],
    "no-failures": ["Nothing fails in the latest results", null],
    stable: ["No unstable tests", "Every test with enough history is stable."],
    "no-recurring": ["No recurring causes", "No failure cause has repeated across runs."],
    clear: ["Nothing needs attention", "No new failures, critical gaps, slower tests or data problems."],
    none: ["Nothing to show", null],
  };
  const [title, text] = TEXT[kind] ?? TEXT.none;
  return h("div", { class: `empty-state empty-${kind}`, "data-empty": kind },
    h("p", { class: "empty-title" }, title), detail ?? text ? h("p", {}, detail ?? text) : null, action);
}

/** The first ``step`` items, then a "Load more" button that adds ``step`` more ("Showing X of Y"). */
export function loadMore(items, render, { step = 25, label = "items", list = "ul", listClass = "" } = {}) {
  const box = h(list, { class: listClass });
  const status = h("p", { class: "list-status", role: "status" });
  const more = h("button", { type: "button", class: "button-quiet" }, "Load more");
  let shown = 0;
  const grow = () => {
    box.append(...items.slice(shown, shown + step).map(render));
    shown = Math.min(items.length, shown + step);
    status.textContent = `Showing ${n(shown)} of ${n(items.length)} ${label}`;
    more.hidden = shown >= items.length;
  };
  more.addEventListener("click", grow);
  grow();
  return h("div", { class: "load-more" }, box, items.length > step ? [status, more] : null);
}

/** Section placeholder shown at once on navigation, so old content never sits under a new heading. */
export function skeleton(title) {
  return [
    h("p", { class: "eyebrow" }, "Report"),
    h("h1", {}, title),
    h("div", { class: "skeleton-grid", "aria-hidden": "true" },
      [0, 1, 2, 3].map(() => h("div", { class: "skeleton skeleton-tile" })),
      h("div", { class: "skeleton skeleton-wide" }), h("div", { class: "skeleton skeleton-wide" })),
    h("p", { class: "visually-hidden", role: "status" }, `Loading ${title}…`),
  ];
}
