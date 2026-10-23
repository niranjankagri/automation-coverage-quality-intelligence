// DOM helpers for the report. Every value is written as text (never as HTML), so imported test names
// and failure messages cannot inject markup.

export const OUTCOMES = ["passed", "failed", "error", "skipped"];

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
