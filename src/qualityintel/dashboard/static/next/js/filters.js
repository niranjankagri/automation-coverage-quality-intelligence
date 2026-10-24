// The filter bar (docs/report-ui.md): Repository > Test type > Browser / Environment > Dates. Choices
// come from the recorded combinations (/api/report/options), so the bar never offers an empty one;
// changing a parent drops child choices it does not have. Freshness of the data sits beside it.

import { KIND_LABELS, formatDate, h, n, repoName } from "./dom.js";

// Older than this, the latest collection is called stale (the live check allows 30 hours too)
const STALE_HOURS = 30;
const LEVELS = ["repository", "kind", "browser", "environment"];
// Phones: the filters fold behind a toggle; it stays open or closed across sections
let expanded = false;
const LABELS = { repository: "Repository", kind: "Test type", browser: "Browser", environment: "Environment", job: "Job", since: "From", until: "To" };

/** Options matching the scope on the given levels (an unset level matches everything). */
const within = (options, scope, levels) => options.filter((o) => levels.every((key) => !scope[key] || (o[key] ?? "") === scope[key]));

/** The scope with every child choice that does not exist under its parents removed. */
export function narrow(scope, options) {
  const next = { ...scope };
  LEVELS.forEach((key, i) => {
    if (i && next[key] && !within(options, next, LEVELS.slice(0, i)).some((o) => o[key] === next[key])) delete next[key];
  });
  return next;
}

/** True when no recorded combination has every chosen level (only possible from a typed address). */
export const unsupported = (scope, options) => options.length > 0 && LEVELS.some((key) => scope[key]) && !within(options, scope, LEVELS).length;

const distinct = (values) => [...new Set(values.filter(Boolean))].sort();
const label = (key, value) => (key === "kind" ? KIND_LABELS[value] ?? value : key === "repository" ? repoName(value) : value);

/**
 * The bar for ``state``; ``go(scope)`` navigates with a new scope, ``refresh()`` reloads the data.
 * ``facts`` holds the options, /api/status and /api/health (any may be missing if the API failed).
 */
export function filterBar(state, facts, go, refresh) {
  const options = facts.options ?? [];
  const scope = state.scope;
  const change = (key, value) => {
    const next = { ...scope, [key]: value };
    if (key === "repository") delete next.job; // a job belongs to one repository
    go(narrow(next, options));
  };
  const select = (key, values, allLabel, extra = {}) => {
    const el = h("select", { id: `filter-${key}`, ...extra },
      h("option", { value: "" }, allLabel),
      values.map((value) => h("option", { value, title: value }, label(key, value))));
    el.value = scope[key] ?? "";
    if (el.value !== (scope[key] ?? "")) el.append(h("option", { value: scope[key] }, label(key, scope[key])));
    el.value = scope[key] ?? "";
    if (scope[key]) el.title = scope[key]; // full name, also when the option text is shortened
    el.addEventListener("change", () => change(key, el.value));
    return h("label", { class: "field" }, h("span", { class: "field-label" }, LABELS[key]), el);
  };

  const repositories = distinct(options.map((o) => o.repository));
  const kinds = distinct(within(options, scope, ["repository"]).map((o) => o.kind));
  const browsers = distinct(within(options, scope, ["repository", "kind"]).map((o) => o.browser));
  const environments = distinct(within(options, scope, ["repository", "kind", "browser"]).map((o) => o.environment));
  const date = (key) => {
    const input = h("input", { type: "date", id: `filter-${key}`, value: scope[key] ?? "" });
    input.addEventListener("change", () => change(key, input.value));
    return h("label", { class: "field field-date" }, h("span", { class: "field-label" }, LABELS[key]), input);
  };

  const chips = Object.keys(LABELS).filter((key) => scope[key]).map((key) => {
    const remove = h("button", { type: "button", class: "chip chip-active", "aria-label": `Remove ${LABELS[key]} ${label(key, scope[key])}`, title: scope[key] },
      h("span", { class: "chip-key" }, `${LABELS[key]}:`), label(key, scope[key]), h("span", { "aria-hidden": "true" }, " ×"));
    remove.addEventListener("click", () => {
      const next = { ...scope };
      delete next[key];
      // Removing a parent keeps children only when they still exist without it
      go(narrow(next, options));
    });
    return remove;
  });
  const reset = h("button", { type: "button", class: "button-quiet" }, "Reset all");
  reset.addEventListener("click", () => go({}));

  const active = Object.keys(LABELS).filter((key) => scope[key]).length;
  const toggle = h("button", { type: "button", class: "button-quiet filter-toggle", "aria-expanded": String(expanded), "aria-controls": "filter-body" },
    active ? `Filters (${active} active)` : "Filters");
  const body = h("div", { class: "filter-body", id: "filter-body" });
  toggle.addEventListener("click", () => {
    expanded = !expanded;
    toggle.setAttribute("aria-expanded", String(expanded));
  });
  body.append(
    h("div", { class: "filter-row" },
      select("repository", repositories, "All repositories", { "aria-label": "Repository" }),
      select("kind", kinds, "All test types", { "aria-label": "Test type", title: "Test types come from the job naming conventions (docs/report-ui.md)" }),
      browsers.length > 1 || scope.browser ? select("browser", browsers, "All browsers", { "aria-label": "Browser" }) : null,
      environments.length > 1 || scope.environment ? select("environment", environments, "All environments", { "aria-label": "Environment" }) : null,
      date("since"), date("until")),
    ...(chips.length ? [h("div", { class: "chip-row", role: "group", "aria-label": "Active filters" }, chips, reset)] : []));
  return h("section", { class: "filterbar", "aria-label": "Filters" },
    toggle,
    body,
    freshness(facts, refresh),
    unsupported(scope, options)
      ? h("p", { class: "notice notice-warning", role: "status" }, "No collected run has this combination of filters. ",
          (() => { const b = h("button", { type: "button", class: "button-quiet" }, "Reset filters"); b.addEventListener("click", () => go({})); return b; })())
      : null);
}

/** "Last collected … · complete" with Refresh; stale or incomplete collections are said plainly. */
function freshness(facts, refresh) {
  const status = facts.status;
  const button = h("button", { type: "button", class: "button-quiet", id: "refresh" }, "Refresh");
  button.addEventListener("click", refresh);
  if (!status) return h("div", { class: "freshness" }, "Data freshness is unknown (status not available). ", button);
  const parts = [];
  const warnings = [];
  if (status.latest_collection_at) {
    const hours = (Date.now() - Date.parse(status.latest_collection_at)) / 3600000;
    parts.push(`Last collected ${formatDate(status.latest_collection_at)}`);
    if (hours > STALE_HOURS) warnings.push(`Collection stale: the latest is ${Math.round(hours)} hours old.`);
  } else {
    parts.push(`Imported result files, loaded ${formatDate(status.loaded_at)} (no CI collection)`);
  }
  const incomplete = status.incomplete_collections_7d ?? 0;
  parts.push(incomplete ? `${n(incomplete)} incomplete collection(s) in 7 days` : status.latest_collection_at ? "collections complete" : null);
  if (incomplete) warnings.push(`Collection incomplete: ${n(incomplete)} pipeline(s) in 7 days are missing jobs or reports, so some results may be absent.`);
  if (status.stale) warnings.push(`The data could not be reloaded${status.last_error ? `: ${status.last_error}` : ""}; figures are from ${formatDate(status.loaded_at)}.`);
  return h("div", { class: "freshness-box" },
    h("div", { class: "freshness" }, h("span", {}, parts.filter(Boolean).join(" · ")), button),
    warnings.length
      ? h("details", { class: "notice notice-warning" }, h("summary", {}, warnings[0]),
          warnings.slice(1).map((w) => h("p", {}, w)),
          status.collection_problems?.length ? h("ul", {}, status.collection_problems.slice(0, 5).map((p) => h("li", {}, p))) : null,
          h("p", {}, h("a", { href: "/classic/#/collection" }, "Open the collection page")))
      : null);
}
