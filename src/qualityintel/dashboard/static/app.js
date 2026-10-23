// Quality Intelligence dashboard: a small hash-routed single page over the JSON API.
// Every number shown comes from the API; this file only fetches, filters the URL and renders.
// All text is set with textContent (test names contain quotes, brackets and < >).
"use strict";

const FILTERS = ["repository", "feature", "owner", "criticality", "test_type", "framework", "environment", "browser", "build", "job", "since", "until"];
const RUN_FILTERS = ["repository", "framework", "environment", "browser", "build", "job", "since", "until"];
const FILTER_NAMES = { repository: "Repository", feature: "Feature", owner: "Owner", criticality: "Criticality", test_type: "Test type", framework: "Framework", environment: "Environment", browser: "Browser", build: "Build", job: "Job", since: "From", until: "To" };
const VIEW_FILTER_NAMES = { suite: "Suite", status: "Status", coverage_status: "Coverage", execution_status: "Execution", observed: "Observed evidence", stale: "Stale evidence", outcome: "Latest outcome", state: "Finding state", kind: "Finding type" };
const OUTCOMES = ["passed", "failed", "error", "skipped"];
const view = document.getElementById("view");
const statusLine = document.getElementById("status");

// ---- tiny DOM helper -------------------------------------------------------------------

/** Create an element: h("a", {href: "#/"}, "text", childNode). Strings become text nodes. */
function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (name === "class") el.className = value;
    else el.setAttribute(name, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === undefined || child === null || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

/** Status badge; the CSS class is the status with spaces replaced (e.g. "not run"). */
function badge(text) {
  return h("span", { class: `badge ${String(text).replaceAll(" ", "-")}` }, text);
}

function formatDate(iso) {
  if (!iso) return "–";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "Invalid date";
  return d.toISOString().slice(0, 16).replace("T", " ") + " UTC";
}

function formatSeconds(value) {
  return value === null || value === undefined ? "–" : `${value.toFixed(value < 10 ? 2 : 1)} s`;
}

let tableCount = 0;

/** A cell for a spreadsheet: one line, and text a spreadsheet would run as a formula made inert. */
function csvCell(text) {
  const flat = text.replace(/\s+/g, " ").trim();
  const safe = /^[=+\-@]/.test(flat) ? `'${flat}` : flat;
  return /[",;\n]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

/**
 * Data table. Every column sorts (a button in its header). With 6 or more rows a toolbar adds a
 * row filter, a CSV download of the filtered and sorted rows, and a column chooser; long tables
 * show 50 rows per page. Sorting and filtering only reorder what the API returned: no figure is
 * computed here.
 */
function table(headers, rows, emptyText, options = {}) {
  rows = rows.flat().filter(Boolean);
  if (!rows.length) return h("div", { class: "table-wrap" }, h("p", { class: "empty" }, emptyText));
  const id = ++tableCount;
  const labels = headers.map((x) => x.label ?? x);
  const tools = options.tools ?? rows.length >= 6;
  const pageSize = options.pageSize ?? 50;
  const state = { col: null, dir: 1, page: 0, needle: "", hidden: new Set() };
  const tbody = h("tbody", {});
  const ths = headers.map((x, i) => {
    const th = h("th", { scope: "col", class: x.num ? "num" : null });
    if (!labels[i]) return th;
    const button = h("button", { type: "button", class: "sort" }, labels[i]);
    button.addEventListener("click", () => {
      state.dir = state.col === i ? -state.dir : 1;
      state.col = i;
      draw();
    });
    th.append(button);
    return th;
  });
  const value = (tr, i) => {
    const text = (tr.children[i]?.textContent ?? "").trim();
    if (!headers[i].num) return text.toLowerCase();
    const match = text.replace(/,/g, "").match(/-?\d+(\.\d+)?/);
    return match ? parseFloat(match[0]) : -Infinity;
  };
  const chosen = () => {
    let list = state.needle ? rows.filter((tr) => tr.textContent.toLowerCase().includes(state.needle)) : rows;
    if (state.col !== null) {
      const i = state.col;
      list = [...list].sort((a, b) => {
        const x = value(a, i);
        const y = value(b, i);
        return (x < y ? -1 : x > y ? 1 : 0) * state.dir;
      });
    }
    return list;
  };
  const pager = h("span", { class: "pager", "aria-live": "polite" });
  const prev = h("button", { type: "button", class: "ghost" }, "Previous");
  const next = h("button", { type: "button", class: "ghost" }, "Next");
  prev.addEventListener("click", () => { state.page -= 1; draw(); });
  next.addEventListener("click", () => { state.page += 1; draw(); });
  const showColumns = (tr) => [...tr.children].forEach((cell, i) => (cell.style.display = state.hidden.has(i) ? "none" : ""));
  function draw() {
    const list = chosen();
    const pages = Math.max(1, Math.ceil(list.length / pageSize));
    state.page = Math.max(0, Math.min(state.page, pages - 1));
    const first = state.page * pageSize;
    const shown = list.slice(first, first + pageSize);
    shown.forEach(showColumns);
    tbody.replaceChildren(...shown);
    ths.forEach((th, i) => {
      th.style.display = state.hidden.has(i) ? "none" : "";
      if (state.col === i) th.setAttribute("aria-sort", state.dir === 1 ? "ascending" : "descending");
      else th.removeAttribute("aria-sort");
    });
    pager.textContent = list.length ? `Rows ${first + 1}–${first + shown.length} of ${list.length}${list.length < rows.length ? ` (filtered from ${rows.length})` : ""}` : `No row matches (of ${rows.length})`;
    prev.disabled = state.page === 0;
    next.disabled = state.page >= pages - 1;
    pagerBox.hidden = list.length <= pageSize && !state.needle;
  }
  const pagerBox = h("div", { class: "pagerbox" }, pager, " ", prev, " ", next);
  const bar = [];
  if (tools) {
    const searchId = options.searchId ?? `table-filter-${id}`;
    const search = h("input", { type: "search", id: searchId, placeholder: options.searchPlaceholder ?? "text in any column" });
    search.addEventListener("input", () => { state.needle = search.value.trim().toLowerCase(); state.page = 0; draw(); });
    const csv = h("button", { type: "button", class: "ghost" }, "Download CSV");
    csv.addEventListener("click", () => {
      const columns = labels.map((_, i) => i).filter((i) => !state.hidden.has(i));
      const lines = [columns.map((i) => csvCell(String(labels[i]))).join(","), ...chosen().map((tr) => columns.map((i) => csvCell(tr.children[i]?.textContent ?? "")).join(","))];
      const blob = new Blob([`${lines.join("\r\n")}\r\n`], { type: "text/csv;charset=utf-8" });
      const a = h("a", { href: URL.createObjectURL(blob), download: `${(options.name ?? document.title.split(" · ")[0]).replace(/[^\w.-]+/g, "-").toLowerCase()}.csv` });
      document.body.append(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
    bar.push(h("label", { for: searchId }, options.searchLabel ?? "Filter rows", search), csv);
    if (labels.filter(Boolean).length >= 5) {
      const boxes = labels.map((label, i) =>
        label
          ? h("label", { class: "inline" }, (() => {
              const box = h("input", { type: "checkbox", checked: true });
              box.addEventListener("change", () => { if (box.checked) state.hidden.delete(i); else state.hidden.add(i); draw(); });
              return box;
            })(), ` ${label}`)
          : null,
      );
      bar.push(h("details", { class: "columns" }, h("summary", {}, "Columns"), h("div", {}, boxes)));
    }
  }
  draw();
  return h(
    "div",
    { class: "table-block" },
    bar.length ? h("div", { class: "toolbar table-tools" }, bar) : null,
    h("div", { class: "table-wrap" }, h("table", {}, h("thead", {}, h("tr", {}, ths)), tbody)),
    pagerBox,
  );
}

// ---- routing and filters ---------------------------------------------------------------

/** Current route: path parts and query parameters from location.hash. */
function route() {
  const raw = location.hash.replace(/^#/, "") || "/";
  const [path, query = ""] = raw.split("?");
  return { parts: path.split("/").filter(Boolean).map(decodeURIComponent), params: new URLSearchParams(query) };
}

/** Link to a path, keeping the active filters. */
function link(path, extra = {}) {
  const params = new URLSearchParams();
  const current = route().params;
  for (const name of FILTERS) if (current.get(name)) params.set(name, current.get(name));
  // A value sets the parameter, null removes a kept filter (breadcrumbs going up), empty is ignored
  for (const [name, value] of Object.entries(extra)) {
    if (value === null) params.delete(name);
    else if (value) params.set(name, value);
  }
  const query = params.toString();
  return `#${path}${query ? `?${query}` : ""}`;
}

/** Link into an entity investigation and keep the current filtered result view available as Back. */
function drillLink(path, extra = {}) {
  const { parts, params } = route();
  params.delete("from"); // Avoid nesting prior return URLs into every deeper investigation.
  const query = params.toString();
  const from = `#/${parts.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
  return link(path, { ...extra, from: from || "#/" });
}

/** API query string from the route's filters (only the names the endpoint understands). */
function apiQuery(names, extra = {}) {
  const params = new URLSearchParams();
  const current = route().params;
  for (const name of names) if (current.get(name)) params.set(name, current.get(name));
  for (const [name, value] of Object.entries(extra)) if (value) params.set(name, value);
  const query = params.toString();
  return query ? `?${query}` : "";
}

async function api(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) {
    let detail = response.statusText;
    try {
      detail = (await response.json()).detail ?? detail;
    } catch (_) {
      /* not JSON */
    }
    throw new Error(`${response.status}: ${typeof detail === "string" ? detail : JSON.stringify(detail)}`);
  }
  return response.json();
}

async function loadFacets() {
  const facets = await api("/api/facets");
  for (const select of document.querySelectorAll("#filters select")) {
    select.replaceChildren(h("option", { value: "" }, "All"), ...facets[select.dataset.facet].map((v) => h("option", { value: v }, v)));
  }
  syncFilterForm();
}

function syncFilterForm() {
  const params = route().params;
  for (const field of document.querySelectorAll("#filters select, #filters input")) {
    // Never overwrite the field someone is editing (a re-render can land while they type)
    if (field !== document.activeElement) field.value = params.get(field.name) ?? "";
  }
}

function applyFilter(field) {
  const { parts, params } = route();
  if (field.value) params.set(field.name, field.value);
  else params.delete(field.name);
  const query = params.toString();
  location.hash = `#/${parts.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
}

// The search box in the header opens the Search page (with the filters of the current view)
document.getElementById("global-search").addEventListener("submit", (event) => {
  event.preventDefault();
  location.hash = link("/search", { q: document.getElementById("global-q").value.trim() });
});

const filterForm = document.getElementById("filters");
filterForm.addEventListener("change", (event) => applyFilter(event.target));
// WebKit reports a picked or typed date with "input" only: a complete or cleared date applies
// too. The fields are recognised by name: engines without a date picker show them as text.
filterForm.addEventListener("input", (event) => {
  const field = event.target;
  const isDate = field.name === "since" || field.name === "until";
  if (isDate && (field.value === "" || /^\d{4}-\d{2}-\d{2}$/.test(field.value))) applyFilter(field);
});

// ---- preferences remembered in this browser (theme, density) ----------------------------------

function remembered(name) {
  try {
    return localStorage.getItem(name);
  } catch (_) {
    return null; // storage blocked: defaults apply
  }
}

function remember(name, value) {
  try {
    if (value) localStorage.setItem(name, value);
    else localStorage.removeItem(name);
  } catch (_) {
    /* applied, not remembered */
  }
}

const themeChoice = document.getElementById("theme-choice");
const compactChoice = document.getElementById("compact-choice");

function applyTheme(value) {
  if (value) document.documentElement.dataset.theme = value;
  else delete document.documentElement.dataset.theme;
}

themeChoice.value = remembered("qi-theme") ?? "";
applyTheme(themeChoice.value);
themeChoice.addEventListener("change", () => {
  applyTheme(themeChoice.value);
  remember("qi-theme", themeChoice.value);
});
compactChoice.checked = remembered("qi-compact") === "on";
document.body.classList.toggle("compact", compactChoice.checked);
compactChoice.addEventListener("change", () => {
  document.body.classList.toggle("compact", compactChoice.checked);
  remember("qi-compact", compactChoice.checked ? "on" : "");
});

const guideDialog = document.getElementById("guide-dialog");
document.getElementById("guide-open").addEventListener("click", () => guideDialog.showModal());
document.getElementById("guide-close").addEventListener("click", () => guideDialog.close());
guideDialog.addEventListener("click", (event) => {
  if (event.target === guideDialog) guideDialog.close();
});
const mobileNavigation = document.querySelector(".mobile-nav");
const filterPanel = document.getElementById("filter-panel");
const smallScreen = window.matchMedia("(max-width: 720px)");
function adaptNavigationToScreen(isSmall) {
  if (isSmall) {
    mobileNavigation.open = false;
    if (!FILTERS.some((name) => route().params.get(name))) filterPanel.open = false;
  } else {
    mobileNavigation.open = true;
  }
}
adaptNavigationToScreen(smallScreen.matches);
smallScreen.addEventListener("change", (event) => adaptNavigationToScreen(event.matches));

/** Set (or remove, with an empty value) filters in the address; the view follows the address. */
function setFilters(values) {
  const { parts, params } = route();
  for (const [name, value] of Object.entries(values)) {
    if (value) params.set(name, value);
    else params.delete(name);
  }
  const query = params.toString();
  location.hash = `#/${parts.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
}

/** One removable chip per active filter, under the filter bar. */
function showActiveFilters() {
  const params = route().params;
  const list = document.getElementById("active-filters");
  const names = [...FILTERS, ...Object.keys(VIEW_FILTER_NAMES)];
  const active = names.filter((name) => params.get(name));
  list.replaceChildren(
    ...active.map((name) => {
      const label = FILTER_NAMES[name] ?? VIEW_FILTER_NAMES[name];
      const value = params.get(name);
      const display = name === "observed" || name === "stale" ? (value === "true" ? "yes" : "no") : value;
      const remove = h("button", { type: "button", class: "chip-remove", "aria-label": `Remove filter ${label}: ${display}` }, "×");
      remove.addEventListener("click", () => setFilters({ [name]: "" }));
      return h("li", {}, h("span", { class: "chip" }, `${label}: ${display}`, remove));
    }),
  );
  list.hidden = active.length === 0;
  document.getElementById("filter-summary").textContent = active.length ? `${active.length} active` : "All data";
}

for (const button of document.querySelectorAll(".quick-dates button")) {
  button.addEventListener("click", () => {
    const days = Number(button.dataset.days);
    if (!days) return setFilters({ since: "", until: "" });
    const since = new Date(Date.now() - days * 86400000).toISOString().slice(0, 10);
    setFilters({ since, until: "" });
  });
}

document.getElementById("copy-view").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  try {
    await navigator.clipboard.writeText(location.href);
    button.textContent = "Link copied";
  } catch (_) {
    button.textContent = "Copy the address bar to share this view";
  }
  setTimeout(() => (button.textContent = "Copy link to this view"), 2500);
});

document.getElementById("clear-filters").addEventListener("click", () => {
  const { parts, params } = route();
  for (const name of [...FILTERS, ...Object.keys(VIEW_FILTER_NAMES)]) params.delete(name);
  const query = params.toString();
  location.hash = `#/${parts.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
});

document.querySelector(".preset-bar").addEventListener("click", (event) => {
  const button = event.target.closest("button[data-preset]");
  if (!button) return;
  const sevenDaysAgo = new Date(Date.now() - 7 * 86400000).toISOString().slice(0, 10);
  const presets = {
    "critical-gaps": () => (location.hash = link("/attention", { kind: "critical gap" })),
    "recent-failures": () => (location.hash = link("/tests", { outcome: "failed", since: sevenDaysAgo, until: "" })),
    "incomplete-pipelines": () => (location.hash = link("/pipelines", { status: "incomplete" })),
    "stale-evidence": () => (location.hash = link("/requirements", { stale: "true", status: "", coverage_status: "", execution_status: "" })),
  };
  presets[button.dataset.preset]?.();
});

// ---- views -----------------------------------------------------------------------------

function helpTip(label, explanation) {
  return h("details", { class: "help-tip" },
    h("summary", { "aria-label": `Definition of ${label}` }, "?"),
    h("div", { class: "help-popover" }, h("strong", {}, label), h("p", {}, explanation)),
  );
}

function metricCard(label, ratio, href, detail, definition = "") {
  const percent = ratio.percent;
  const card = h(
    href ? "a" : "div",
    { class: "card", href },
    h("div", { class: "label" }, label),
    h("div", { class: "value" }, percent === null ? "n/a" : `${percent.toFixed(1)} %`),
    h("div", { class: "detail" }, `${ratio.numerator} of ${ratio.denominator}${detail ? ` · ${detail}` : ""}`),
    meter(percent ?? 0),
  );
  return definition ? h("div", { class: "card-shell" }, card, helpTip(label, definition)) : card;
}

/** Bar for a percentage. The width is set through the CSSOM: the CSP forbids style attributes. */
function meter(percent) {
  const bar = h("span");
  bar.style.width = `${percent}%`;
  return h("div", { class: "meter", "aria-hidden": "true" }, bar);
}

function countCard(label, value, href, detail, definition = "") {
  const card = h(href ? "a" : "div", { class: "card", href }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), detail ? h("div", { class: "detail" }, detail) : null);
  return definition ? h("div", { class: "card-shell" }, card, helpTip(label, definition)) : card;
}

/** Requirement ids as links; ``tone`` colours them (e.g. "critical", "failing"). */
function idChips(ids, tone) {
  if (!ids.length) return h("p", { class: "lead" }, "None.");
  return h("ul", { class: "chips" }, ids.map((id) => h("li", {}, h("a", { href: drillLink(`/requirement/${encodeURIComponent(id)}`) }, h("span", { class: `badge ${tone}` }, id)))));
}

const STATE_TEXT = { ready: "Ready", "at risk": "At risk", blocked: "Blocked", unknown: "Unknown" };

function readinessEvidence(reason) {
  const text = reason.toLowerCase();
  if (text.includes("flaky candidate")) return h("a", { href: link("/stability") }, "View stability evidence");
  if (text.includes("incomplete pipeline")) return h("a", { href: link("/pipelines", { status: "incomplete" }) }, "View incomplete pipelines");
  if (text.includes("critical") && (text.includes("automation") || text.includes("gap"))) return h("a", { href: link("/attention", { kind: "critical gap" }) }, "View critical gap evidence");
  if (text.includes("refresh") || text.includes("stale")) return h("a", { href: link("/collection") }, "Review collection and refresh status");
  if (text.includes("fail") || text.includes("error")) return h("a", { href: link("/tests", { outcome: "failed" }) }, "Review failed test results");
  return null;
}

function readinessPanel(r) {
  return h(
    "section",
    { class: `readiness ${r.state.replaceAll(" ", "-")}`, "aria-labelledby": "readiness-title" },
    h("h2", { id: "readiness-title" }, "Release status: ", badge(STATE_TEXT[r.state] ?? r.state)),
    h("p", { class: "sub" }, r.gate_name ? `Readiness engine result from the "${r.gate_name}" gate and the documented warnings it does not measure (docs/readiness.md).` : "No release gate is configured for this dashboard; readiness is unknown without a gate."),
    h("ul", { class: "reasons" }, r.reasons.map((reason) => h("li", {}, reason, readinessEvidence(reason) ? [" ", readinessEvidence(reason)] : null))),
    // Every criterion the status was derived from, computed server-side (docs/readiness.md, Scorecard)
    h(
      "details",
      {},
      h("summary", {}, `Scorecard: ${r.scorecard.length} criteria, ${r.scorecard.filter((x) => x.effect !== "none").length} affect the status`),
      table(
        ["Criterion", "Source", "Measured", "Threshold", "Result", "Effect on status"],
        r.scorecard.map((x) => h("tr", { class: x.effect !== "none" ? "failing-rule" : null },
          h("td", {}, x.name, h("span", { class: "sub" }, x.explanation), x.route ? h("a", { class: "sub", href: link(x.route, x.params) }, "View supporting evidence") : null),
          h("td", {}, x.source),
          h("td", {}, x.measured),
          h("td", {}, x.threshold),
          h("td", {}, x.result),
          h("td", {}, x.effect),
        )),
        "",
      ),
    ),
    h(
      "div",
      { class: "cards" },
      // Coverage and pass rate have their own cards below; these are the figures only shown here
      countCard("Test executions", r.executions, link("/tests"), "latest run per context, in scope"),
      countCard("Critical without automation", r.critical_without_automation, link("/attention", { kind: "critical gap" }), "catalog requirements without a linked automated case", "Critical requirements in scope that have no automated linked test case; it is a catalog gap, not an execution failure."),
      countCard("Flaky candidates", r.flaky_candidates, link("/stability"), "suspected mixed-outcome patterns", "Tests classified as flaky candidates by the history rules. A candidate is not a proven cause."),
      countCard("Incomplete pipelines (7 days)", r.incomplete_pipelines, link("/pipelines", { status: "incomplete" }), "collection records in the last 7 days", "Collection attempts with missing jobs or reports in the last seven days; this is collection completeness, separate from test outcome."),
      countCard("Latest collection record", r.latest_collection_at ? formatDate(r.latest_collection_at) : "–", link("/collection"), r.latest_collection_at ? "per-repository freshness is shown in Operations" : "no collection recorded", "Timestamp of the newest collection record, which may be incomplete. See Operations for per-repository freshness and the last complete collection."),
    ),
  );
}

// Coverage gaps in priority order, one group per owner (docs/traceability.md, Prioritised gaps)
function prioritisedGaps(g) {
  return [
    h("h2", {}, `Coverage gaps by owner (${g.total})`),
    h("p", { class: "sub" }, `Order: ${g.order}.`),
    g.owners.length
      ? g.owners.map((o, i) => h("details", { class: "gap-owner", open: i === 0 ? "" : null },
          h("summary", {}, `${o.owner}: ${o.gaps.length} gap(s), most urgent #${o.gaps[0].rank}`),
          table(
            [{ label: "Rank", num: true }, "Requirement", "Criticality", "Risk", "Gap", "Linked test cases"],
            o.gaps.map((x) => h("tr", {},
              h("td", { class: "num" }, x.rank),
              h("td", {}, h("a", { class: "key", href: drillLink(`/requirement/${encodeURIComponent(x.requirement_id)}`) }, x.requirement_id), h("span", { class: "sub" }, x.title)),
              h("td", {}, x.criticality ?? "unspecified"),
              h("td", {}, x.risk ?? "unspecified"),
              h("td", {}, x.kind),
              h("td", {}, x.case_statuses.join(", ") || "none"),
            )),
            "",
          ),
        ))
      : h("p", { class: "empty" }, "Every requirement in scope has an automated test case."),
  ];
}

async function overview() {
  const [s, r, collection, builds, gaps] = await Promise.all([
    api(`/api/summary${apiQuery(FILTERS)}`),
    api(`/api/readiness${apiQuery(FILTERS)}`),
    api("/api/collection"),
    api(`/api/builds${apiQuery(RUN_FILTERS)}`),
    api(`/api/gaps${apiQuery(FILTERS)}`),
  ]);
  const comparison = builds.length > 1
    ? await api(`/api/compare${apiQuery(RUN_FILTERS, { base: builds[builds.length - 2], head: builds[builds.length - 1] })}`)
    : null;
  const c = s.outcome_counts;
  const freshRepositories = collection.repositories.filter((repository) => repository.fresh).length;
  const collectionRatio = collection.repositories.length ? `${freshRepositories} of ${collection.repositories.length}` : "n/a";
  const releaseSummary = [
    `Release readiness: ${STATE_TEXT[r.state] ?? r.state}`,
    `Gate: ${r.gate_name ?? "not configured"}`,
    `Observed reasons: ${r.reasons.join("; ") || "none recorded"}`,
    `Requirement coverage: ${s.requirement_coverage.text}`,
    `Automation coverage: ${s.automation_coverage.text}`,
    `Automated requirement coverage: ${s.automated_requirement_coverage.text}`,
    `Execution pass rate: ${s.pass_rate.text}`,
    `Failed results in the latest snapshot: ${c.failed}; errors: ${c.error}; skipped: ${c.skipped}`,
    `Critical requirements without automation: ${s.uncovered_critical.length}`,
    `Repositories within the ${collection.expected_hours} hour collection window: ${collectionRatio}`,
    `Scope follows the filters in this dashboard URL. The catalog notice and data freshness bar apply.`,
  ].join("\n");
  return [
    h("h1", {}, "Overview"),
    h("details", { class: "onboarding", open: "" },
      h("summary", {}, "Start here: how to read this dashboard"),
      h("ol", {},
        h("li", {}, "Choose a scope with the filters or open a quick view."),
        h("li", {}, "Read release readiness with its reasons, then check each metric's denominator and limitation."),
        h("li", {}, "Open a finding or chart count to follow its evidence into a test, requirement, run or pipeline."),
        h("li", {}, "Use Operations to check collection freshness separately from test execution quality."),
        h("li", {}, "Filters stay in the URL; use Copy link to this view to share the current scope."),
      ),
    ),
    readinessPanel(r),
    h("p", { class: "lead" }, "Coverage comes from the requirement catalog; the pass rate comes from the latest run of each framework, environment and browser. They are separate numbers on purpose."),
    h("div", { class: "toolbar executive-actions" },
      copyButton("Copy release summary", releaseSummary),
      h("a", { href: link("/attention") }, "Open action center"),
      h("a", { href: link("/collection") }, "Review operations"),
    ),
    h("h2", {}, "Quick actions"),
    h("div", { class: "quick-actions" },
      h("a", { href: link("/attention", { state: "open" }) }, h("strong", {}, "Investigate open findings"), h("span", { class: "sub" }, "Tests, coverage gaps, pipelines and overdue collections")),
      h("a", { href: link("/requirements", { criticality: "critical" }) }, h("strong", {}, "Review critical requirements"), h("span", { class: "sub" }, `${s.uncovered_critical.length} critical requirement(s) without automation`)),
      h("a", { href: link("/tests", { outcome: "failed" }) }, h("strong", {}, "Review failed results"), h("span", { class: "sub" }, "Latest results in the current run scope")),
      h("a", { href: link("/pipelines", { status: "incomplete" }) }, h("strong", {}, "Review incomplete pipelines"), h("span", { class: "sub" }, `${r.incomplete_pipelines} incomplete collection(s) in the last 7 days`)),
    ),
    h("h2", {}, "Coverage"),
    h(
      "div",
      { class: "cards" },
      countCard("Requirements in scope", s.requirements_total, link("/requirements"), `${s.requirements_with_tests} with linked test cases`, "Unique requirements in the active catalog scope; this is the denominator for requirement coverage."),
      metricCard("Requirement coverage", s.requirement_coverage, link("/requirements", { coverage_status: "no tests" }), "with at least one test case", "Requirements with one or more linked test cases divided by requirements in scope. A linked manual or planned case counts."),
      metricCard("Automation coverage", s.automation_coverage, link("/requirements", { coverage_status: "not automated" }), "linked test cases automated", "Automated linked test cases divided by all linked test cases. Unlinked cases are excluded."),
      metricCard("Automated requirement coverage", s.automated_requirement_coverage, link("/requirements", { coverage_status: "not automated" }), "with an automated test", "Requirements with at least one linked automated test case divided by requirements in scope."),
      countCard("Collection freshness", collectionRatio, link("/collection"), `${collection.expected_hours} hour window across all collected repositories`, "This global Operations measure counts each repository whose latest collection record is within the server's expected window. It does not follow run filters and is separate from test pass rate."),
    ),
    h("h2", {}, "Execution (latest runs)"),
    h(
      "div",
      { class: "cards" },
      metricCard("Execution pass rate", s.pass_rate, link("/tests"), "skipped results are not counted", "Passed results divided by passed, failed and error results in the latest snapshot. Skips are excluded; this measures executions, not requirement coverage."),
      countCard("Passed", c.passed, link("/tests", { outcome: "passed" }), "latest snapshot results", "Count of passed result records in the latest snapshot, not unique test identifiers."),
      countCard("Failed", c.failed, link("/tests", { outcome: "failed" }), "latest snapshot results", "Count of failed result records in the latest snapshot, not unique test identifiers."),
      countCard("Errors", c.error, link("/tests", { outcome: "error" }), "latest snapshot results", "Count of error result records in the latest snapshot, not unique test identifiers."),
      countCard("Skipped", c.skipped, link("/tests", { outcome: "skipped" }), "latest snapshot results", "Count of skipped result records in the latest snapshot; skips do not enter the pass-rate denominator."),
    ),
    s.snapshot.length
      ? table(
          ["Run", "Framework", "Browser", "Build", "Started", { label: "Pass rate", num: true }],
          s.snapshot.map((r) =>
            h("tr", {}, h("td", {}, h("a", { href: drillLink(`/run/${r.run_id}`) }, r.source)), h("td", {}, r.context.framework ?? "–"), h("td", {}, r.context.browser ?? "–"), h("td", {}, r.context.build ?? "–"), h("td", { class: "nowrap" }, formatDate(r.started_at)), h("td", { class: "num" }, r.pass_rate.text)),
          ),
          "",
        )
      : h("p", { class: "empty" }, "No runs in this scope (or no result files were loaded), so there is no execution status."),
    h("h2", {}, "Build comparison"),
    !comparison
      ? h("p", { class: "empty" }, "At least two builds are needed in this run scope; no change summary is available.")
      : !comparison.comparable
        ? h("p", { class: "empty" }, `No change summary shown for ${comparison.base.build} to ${comparison.head.build}: these builds share no suite in this scope. `, h("a", { href: link("/compare", { base: comparison.base.build, head: comparison.head.build }) }, "Review build comparability"))
        : [
            h("p", { class: "sub" }, `Observed changes from ${comparison.base.build} to ${comparison.head.build} across ${comparison.compared_contexts.length} shared suite(s). Counts include tests from shared suites only.`),
            table(
              ["Change in shared suites", { label: "Tests", num: true }],
              Object.entries(comparison.category_counts).map(([category, count]) => h("tr", {}, h("td", {}, h("a", { href: link("/compare", { base: comparison.base.build, head: comparison.head.build, change: category }) }, category)), h("td", { class: "num" }, count))),
              "The builds share suites, and no test changes were recorded.",
              { tools: false },
            ),
            h("p", { class: "sub" }, h("a", { href: link("/compare", { base: comparison.base.build, head: comparison.head.build }) }, "Open the full build comparison")),
          ],
    h("h2", {}, `Critical requirements without automation (${s.uncovered_critical.length})`),
    idChips(s.uncovered_critical.map((r) => r.id), "critical"),
    ...prioritisedGaps(gaps),
    h("h2", {}, `Failing requirements (${s.failing_requirements.length})`),
    idChips(s.failing_requirements.map((r) => r.id), "failing"),
    h("h2", {}, "Other gaps"),
    h(
      "div",
      { class: "cards" },
      countCard("Requirements without tests", s.requirements_without_tests.length, link("/requirements", { status: "no tests" })),
      countCard("Requirements without automation", s.requirements_without_automation.length, link("/requirements", { status: "not automated" })),
      countCard("Automated cases linked to nothing", s.unlinked_automated_cases.length, null, s.unlinked_automated_cases.join(", ") || "none"),
      countCard("Automated cases without results", s.automated_cases_without_results.length, null, s.automated_cases_without_results.join(", ") || "none"),
      countCard("Results matching no test case", s.unmatched_results, link("/tests")),
    ),
  ];
}

/** One matrix table; every nonzero cell links to the exact requirement field it counts. */
function matrixTable(title, rows, param) {
  const coverage = ["no tests", "not automated", "automated"];
  const execution = ["failing", "not run", "skipped", "passing", "not automated"];
  const drill = (query, count) => count ? h("a", { href: link("/requirements", { ...query, from: location.hash }) }, String(count)) : "0";
  return [
    h("h3", {}, title),
    table(
      [title.replace("By ", ""), { label: "Total", num: true }, ...coverage.map((c) => ({ label: c, num: true })), ...execution.map((e) => ({ label: e, num: true })), { label: "Stale evidence", num: true }],
      rows.map((r) =>
        h(
          "tr",
          {},
          h("td", {}, r.group),
          h("td", { class: "num" }, String(r.total)),
          coverage.map((c) => h("td", { class: "num" }, drill({ coverage_status: c, [param]: r.group }, r.coverage[c] ?? 0))),
          execution.map((e) => h("td", { class: "num" }, drill({ execution_status: e, [param]: r.group }, r.execution[e] ?? 0))),
          h("td", { class: "num" }, drill({ stale: "true", [param]: r.group }, r.stale)),
        ),
      ),
      "No requirements in scope.",
      { tools: false },
    ),
  ];
}

function repositoryMatrixTable(rows) {
  const execution = ["failing", "not run", "skipped", "passing", "not automated"];
  const drill = (repository, query, count) => count
    ? h("a", { href: link("/requirements", { repository, observed: "true", ...query, from: location.hash }) }, String(count))
    : "0";
  return [
    h("h3", {}, "By repository (observed test evidence)"),
    h("p", { class: "sub" }, "Requirements are catalog-wide. This view counts only requirements with a linked result observed in that repository; it does not imply that repository is expected to cover every catalog requirement."),
    table(
      ["Repository", { label: "Observed requirements", num: true }, ...execution.map((value) => ({ label: value, num: true })), { label: "Stale evidence", num: true }],
      rows.map((row) => h("tr", {},
        h("td", {}, h("a", { href: link("/requirements", { repository: row.repository, observed: "true", from: location.hash }) }, row.repository)),
        h("td", { class: "num" }, drill(row.repository, {}, row.observed_requirements)),
        ...execution.map((status) => h("td", { class: "num" }, drill(row.repository, { execution_status: status }, row.execution[status] ?? 0))),
        h("td", { class: "num" }, drill(row.repository, { stale: "true" }, row.stale)),
      )),
      "No linked requirement results include a repository. Repository-level requirement evidence is unavailable in this scope.",
      { tools: false },
    ),
  ];
}

async function requirementsView() {
  const params = route().params;
  const status = params.get("status") ?? "";
  const coverageStatus = params.get("coverage_status") ?? "";
  const executionStatus = params.get("execution_status") ?? "";
  const observed = params.get("observed") ?? "";
  const stale = params.get("stale") ?? "";
  const query = { status, coverage_status: coverageStatus, execution_status: executionStatus, observed, stale };
  const [rows, matrix] = await Promise.all([api(`/api/requirements${apiQuery(FILTERS, query)}`), api(`/api/requirements/matrix${apiQuery(FILTERS)}`)]);
  const statusSelect = h("select", { id: "status-filter" }, ["", "no tests", "not automated", "automated", "passing", "failing", "not run", "skipped"].map((v) => h("option", { value: v }, v || "Any")));
  statusSelect.value = status || coverageStatus || executionStatus;
  statusSelect.addEventListener("change", () => (location.hash = link("/requirements", { status: statusSelect.value, coverage_status: null, execution_status: null, observed: null, stale: null })));
  return [
    h("h1", {}, "Requirements"),
    h("p", { class: "lead" }, `${rows.length} requirement(s) in scope.`),
    h(
      "details",
      { class: "matrix", open: status || coverageStatus || executionStatus || observed || stale ? null : "" },
      h("summary", {}, "Coverage and execution breakdowns"),
      h("p", { class: "sub" }, `Catalog coverage distinguishes requirements with linked cases from automated cases; execution status comes from the latest run snapshot. Evidence is stale when the latest execution is older than ${matrix.stale_days} days. Each nonzero count opens the matching requirements.`),
      matrixTable("By criticality", matrix.by_criticality, "criticality"),
      matrixTable("By feature", matrix.by_feature, "feature"),
      matrixTable("By owner", matrix.by_owner, "owner"),
      repositoryMatrixTable(matrix.by_repository),
    ),
    h(
      "div",
      { class: "toolbar" },
      h("label", { for: "status-filter" }, "Status", statusSelect),
      h("a", { href: link("/attention", { kind: "critical gap" }) }, "Critical gaps"),
    ),
    h("h2", { id: "requirement-list", class: "visually-hidden" }, "Requirement list"),
    h("section", { "aria-labelledby": "requirement-list" }, table(
      ["Requirement", "Feature", "Owner", "Criticality", { label: "Automated / cases", num: true }, "Coverage", "Execution", "Matched result evidence", "Latest evidence"],
      rows.map((r) =>
        h(
          "tr",
          {},
          h("td", {}, h("a", { href: drillLink(`/requirement/${encodeURIComponent(r.id)}`) }, r.id), h("span", { class: "sub" }, r.title)),
          h("td", {}, r.feature),
          h("td", {}, r.owner),
          h("td", {}, r.criticality === "critical" ? badge("critical") : r.criticality),
          h("td", { class: "num" }, `${r.automated_test_cases} / ${r.test_cases}`),
          h("td", {}, badge(r.coverage_status)),
          h("td", {}, badge(r.execution_status)),
          h("td", {}, badge(r.observed ? "observed" : "not observed")),
          h("td", { class: "nowrap" }, r.last_executed_at ? formatDate(r.last_executed_at) : "none", r.stale ? [" ", badge("stale")] : null),
        ),
      ),
      "No requirements match these filters.",
      { tools: true, name: status ? `requirements-${status}` : "requirements" },
    )),
    h("p", { class: "sub" }, "Coverage over time (recorded catalog snapshots) is on the Trends page."),
  ];
}

/** Table rows for executions; the test column is left out where every row is the same test. */
function executionRows(executions, withTest = true) {
  return executions.map((e) =>
    h(
      "tr",
      {},
      withTest ? h("td", {}, h("a", { class: "key", href: drillLink("/test", { key: e.key }) }, e.key)) : null,
      h("td", {}, `${e.context.framework ?? "–"} / ${e.context.browser ?? "–"}`),
      h("td", { class: "nowrap" }, e.context.build ?? "–", h("span", { class: "sub" }, formatDate(e.started_at))),
      h("td", {}, badge(e.outcome), e.retries ? h("span", { class: "sub" }, `${e.retries} retr${e.retries === 1 ? "y" : "ies"}`) : null),
      h("td", { class: "num" }, formatSeconds(e.duration_seconds)),
      h("td", {}, e.failure ? failureDetails(e.failure) : "–"),
    ),
  );
}

/** Collapsed failure: first line of the message as summary, everything else when opened. */
function failureDetails(failure) {
  const message = failure.message || failure.type || "details";
  const firstLine = message.split("\n")[0];
  const summary = firstLine.length > 160 ? `${firstLine.slice(0, 157)}…` : firstLine;
  const full = [failure.message, failure.text].filter(Boolean).join("\n\n");
  return h("details", {}, h("summary", {}, summary), failure.type ? h("p", { class: "sub" }, failure.type) : null, full ? h("pre", { class: "trace" }, full) : null);
}

const EXECUTION_HEADERS = ["Test", "Framework / browser", "Build", "Outcome", { label: "Duration", num: true }, "Failure"];

function backToResults(defaultLabel, defaultPath) {
  const from = route().params.get("from");
  const safeFrom = from === "#/" || /^#\/(search|attention|requirements|requirement|tests|test|runs|run|pipelines|collection|compare|stability|trends|executions)(\?|$)/.test(from ?? "");
  return h("p", { class: "detail-back" }, h("a", { href: safeFrom ? from : link(defaultPath) }, safeFrom ? "Back to filtered results" : `Back to ${defaultLabel}`));
}

async function requirementDetail(id) {
  const d = await api(`/api/requirements/${encodeURIComponent(id)}${apiQuery(RUN_FILTERS)}`);
  const r = d.requirement;
  return [
    backToResults("Requirements", "/requirements"),
    h("h1", {}, `${r.id}: ${r.title}`),
    r.description ? h("p", { class: "lead" }, r.description) : null,
    h("dl", { class: "meta" }, h("dt", {}, "Feature"), h("dd", {}, r.feature), h("dt", {}, "Owner"), h("dd", {}, r.owner), h("dt", {}, "Criticality"), h("dd", {}, r.criticality), h("dt", {}, "Priority / risk"), h("dd", {}, `${r.priority} / ${r.risk}`), h("dt", {}, "Platforms"), h("dd", {}, r.platforms.join(", ") || "unspecified"), h("dt", {}, "Coverage"), h("dd", {}, badge(r.coverage_status)), h("dt", {}, "Execution"), h("dd", {}, badge(r.execution_status))),
    h("h2", {}, `Test cases (${d.test_cases.length})`),
    d.test_cases.length
      ? d.test_cases.map((c) => [
          h("h2", {}, `${c.id}: ${c.title} `, badge(c.automation_status), " ", badge(c.execution_status)),
          h("p", { class: "lead" }, `Type ${c.test_type}, framework ${c.framework}. Latest executions:`),
          table(EXECUTION_HEADERS, executionRows(c.executions), c.automation_status === "automated" ? "No executions in the loaded runs." : "Not automated: no executions expected."),
        ])
      : h("p", { class: "empty" }, "No test case is linked to this requirement."),
  ];
}

async function testsView() {
  const outcome = route().params.get("outcome") ?? "";
  const rows = await api(`/api/tests${apiQuery(RUN_FILTERS, { outcome })}`);
  const outcomeSelect = h("select", { id: "outcome-filter" }, ["", ...OUTCOMES].map((v) => h("option", { value: v }, v || "Any")));
  outcomeSelect.value = outcome;
  outcomeSelect.addEventListener("change", () => (location.hash = link("/tests", { outcome: outcomeSelect.value })));
  const body = rows.map((r) => {
    const tr = h(
      "tr",
      { "data-key": r.key.toLowerCase() },
      h("td", {}, h("a", { class: "key", href: drillLink("/test", { key: r.key }) }, r.key), r.last_failure ? h("span", { class: "sub" }, `last failure: ${r.last_failure}`) : null),
      h("td", {}, r.frameworks.join(", ")),
      h("td", { class: "num" }, r.executions),
      h("td", { class: "num" }, r.passed),
      h("td", { class: "num" }, r.failed),
      h("td", { class: "num" }, r.errors),
      h("td", { class: "num" }, r.skipped),
      h("td", {}, badge(r.latest_outcome)),
      h("td", {}, r.test_cases.length ? r.test_cases.join(", ") : badge("unmatched")),
    );
    return tr;
  });
  return [
    h("h1", {}, "Tests"),
    h("p", { class: "lead" }, `${rows.length} test(s) across all loaded runs; tests with failures first.`),
    h("div", { class: "toolbar" }, h("label", { for: "outcome-filter" }, "Latest outcome", outcomeSelect)),
    table(["Test", "Framework", { label: "Runs", num: true }, { label: "Passed", num: true }, { label: "Failed", num: true }, { label: "Errors", num: true }, { label: "Skipped", num: true }, "Latest", "Test case"], body, "No tests in the loaded runs match these filters.", { tools: true, searchLabel: "Filter tests by name", searchId: "test-search", searchPlaceholder: "part of the name", name: "tests" }),
  ];
}

/** A button that copies text; says "Copied" (or how to copy by hand when the browser refuses). */
function copyButton(label, text) {
  const button = h("button", { type: "button", class: "ghost copy" }, label);
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(text);
      button.textContent = "Copied";
    } catch (_) {
      button.textContent = "Copy failed: select the text and press Ctrl+C";
    }
    setTimeout(() => (button.textContent = label), 2500);
  });
  return button;
}

async function testHistory() {
  const key = route().params.get("key") ?? "";
  const d = await api(`/api/tests/history${apiQuery(RUN_FILTERS, { key })}`);
  const latest = d.executions[0];
  const oldestFirst = [...d.executions].reverse();
  const labels = oldestFirst.map((e) => `${formatDate(e.started_at)} · ${e.context.build ?? "–"}`);
  const durations = oldestFirst.map((e) => e.duration_seconds);
  const shareLink = `${location.origin}${location.pathname}${link("/test", { key })}`;
  const previous = d.executions[1];
  return [
    backToResults("Tests", "/tests"),
    crumbs([["Tests", link("/tests")], ...pipelineCrumbs(latest.pipeline, latest.workflow, latest.run_id, latest.source), [d.key, null]]),
    h("h1", { class: "key" }, d.key),
    h("div", { class: "toolbar" }, copyButton("Copy test identifier", d.key), copyButton("Copy investigation link", shareLink), summaryButtons("/api/tests/summary", { key })),
    h(
      "dl",
      { class: "meta" },
      h("dt", {}, "Latest result"),
      h("dd", {}, badge(latest.outcome), " ", formatDate(latest.started_at), latest.retries ? ` after ${latest.retries} retr${latest.retries === 1 ? "y" : "ies"}` : ""),
      h("dt", {}, "Previous result"),
      h("dd", {}, previous ? [badge(previous.outcome), " ", formatDate(previous.started_at), ` · build ${previous.context.build ?? "not recorded"}`] : "none in this scope"),
      h("dt", {}, "Context"),
      h("dd", {}, [latest.context.framework, latest.context.environment, latest.context.browser, latest.context.platform].map((v) => v ?? "–").join(" / "), ` · build ${latest.context.build ?? "–"}`),
      h("dt", {}, "Repository / workflow"),
      h("dd", {}, latest.pipeline ? `${latest.pipeline.repository ?? "not recorded"} · ${latest.workflow ?? "workflow not recorded"}` : "not collected from a pipeline"),
      h("dt", {}, "Stability"),
      h("dd", {}, d.stability.length ? h("ul", { class: "reasons" }, d.stability.map((line) => h("li", {}, line))) : "not classified (too few verdicts in the scope)"),
      h("dt", {}, "Source"),
      h("dd", {}, h("a", { href: drillLink(`/run/${latest.run_id}`) }, latest.source), latest.pipeline ? ` · pipeline ${pipelineLabel(latest.pipeline)}` : "", latest.ci_url ? [" · ", external(latest.ci_url, "CI run on GitHub")] : null),
      h("dt", {}, "Requirements"),
      h("dd", {}, d.requirements.length ? d.requirements.map((rid, i) => [i ? ", " : "", h("a", { href: drillLink(`/requirement/${encodeURIComponent(rid)}`) }, rid)]) : "none linked"),
      h("dt", {}, "Test cases"),
      h("dd", {}, d.test_cases.join(", ") || "none (unmatched)"),
      h("dt", {}, "Pattern"),
      h("dd", {}, h("ol", { class: "pattern", "aria-label": `${d.passed} passed, ${d.failed} failed or errored, oldest first` }, oldestFirst.map((e) => h("li", { class: `dot ${e.outcome}`, title: `${formatDate(e.started_at)}: ${e.outcome}` }, e.outcome[0].toUpperCase()))), h("span", { class: "sub" }, `${d.passed} passed, ${d.failed} failed or errored of ${d.executions.length}, oldest first`)),
    ),
    latest.failure ? [h("h2", {}, "Latest failure"), failureDetails(latest.failure)] : null,
    executionComparison(d.executions),
    durations.some((v) => v !== null)
      ? chartFigure("Duration per execution", lineChart(labels, [{ name: "duration", cls: "s-rate", values: durations }], { unit: "s" }), [{ name: "duration", cls: "s-rate", values: durations }], labels, "oldest first", (v) => formatSeconds(v))
      : null,
    h(
      "section",
      { "aria-labelledby": "executions-title" },
      h("h2", { id: "executions-title" }, `Executions (${d.executions.length}, newest first)`),
      table(EXECUTION_HEADERS.slice(1), executionRows(d.executions, false), "No executions."),
    ),
  ];
}

// Each suite's newest build against its previous build on the same branch (docs/history.md)
function latestRegressions(d) {
  const tests = (keys) => [keys.slice(0, 5).map((k, i) => [i ? ", " : null, h("a", { class: "key", href: drillLink("/test", { key: k }) }, k)]), keys.length > 5 ? ` and ${keys.length - 5} more` : null];
  return h(
    "section",
    { "aria-labelledby": "regressions-title" },
    h("h2", { id: "regressions-title" }, `Latest regressions (${d.regressions.length})`),
    h("p", { class: "sub" }, `Each suite's newest build compared with its previous build on the same branch: ${d.compared} suites compared, ${d.single_build} ran in one build only. ${d.notes.join(" ")}`),
    table(
      ["Suite", "Repository · branch", "Builds", "Newly failing", "Recovered", "Runs"],
      d.regressions.map((r) => h("tr", {},
        h("td", {}, r.suite),
        h("td", {}, `${r.repository ?? "not recorded"} · ${r.branch ?? "branch not recorded"}`),
        h("td", { class: "nowrap" }, h("a", { href: link("/compare", { base: r.base_build, head: r.head_build }) }, `${r.base_build} → ${r.head_build}`), r.head_started_at ? h("span", { class: "sub" }, formatDate(r.head_started_at)) : null),
        h("td", {}, tests(r.newly_failing)),
        h("td", { class: "num" }, r.fixed.length),
        h("td", { class: "nowrap" }, h("a", { href: drillLink(`/run/${r.base_run_id}`) }, "previous"), " · ", h("a", { href: drillLink(`/run/${r.head_run_id}`) }, "newest")),
      )),
      "No suite fails a test in its newest build that passed in its previous build.",
    ),
  );
}

async function compareView() {
  const params = route().params;
  const [builds, regressions] = await Promise.all([api(`/api/builds${apiQuery(RUN_FILTERS)}`), api(`/api/regressions${apiQuery(RUN_FILTERS)}`)]);
  const head = params.get("head") ?? builds[builds.length - 1] ?? "";
  const base = params.get("base") ?? builds[builds.length - 2] ?? "";
  const pick = (id, value, other) => {
    const select = h("select", { id }, builds.map((b) => h("option", { value: b }, b)));
    select.value = value;
    select.addEventListener("change", () => (location.hash = link("/compare", other === "base" ? { base: select.value, head } : { base, head: select.value })));
    return select;
  };
  const header = [
    h("h1", {}, "Compare builds"),
    h("p", { class: "lead" }, "Builds are compared only where both ran the same suite (context and job). Builds are listed in the order they first ran."),
    h("div", { class: "toolbar" }, h("label", { for: "base-build" }, "Baseline build", pick("base-build", base, "base")), h("label", { for: "head-build" }, "Comparison build", pick("head-build", head, "head"))),
    // Builds of different repositories never share a suite: say so while all are listed
    params.get("repository") ? null : h("p", { class: "sub" }, "Tip: choose a Repository above to list only its builds; builds of different repositories have no suite in common."),
    latestRegressions(regressions),
  ];
  if (builds.length < 2) return [...header, h("p", { class: "empty" }, "At least two builds are needed in this scope.")];
  if (base === head) return [...header, h("p", { class: "empty" }, "Choose two different builds.")];
  // A link can name a build this scope does not have (pruned, mistyped, or filtered out)
  const unknown = [base, head].filter((b) => !builds.includes(b));
  if (unknown.length) {
    return [...header, h("p", { class: "notice", role: "note" }, `No runs of build ${unknown.join(" or ")} in this scope (it may be filtered out, mistyped or no longer in the history). Choose builds above.`)];
  }
  const d = await api(`/api/compare${apiQuery(RUN_FILTERS, { base, head })}`);
  const side = (title, b) =>
    h(
      "div",
      { class: "card" },
      h("div", { class: "label" }, title),
      h("div", { class: "value" }, b.build),
      h("div", { class: "detail" }, `${b.runs} run(s) · pass rate ${b.pass_rate.text}`),
      h("div", { class: "detail" }, `${b.counts.passed} passed, ${b.counts.failed} failed, ${b.counts.error} errors, ${b.counts.skipped} skipped`),
      h("div", { class: "detail" }, b.requirement_coverage ? `requirement coverage ${b.requirement_coverage.text}` : "no coverage snapshot before this build"),
      h("div", { class: "detail" }, `last run ${formatDate(b.last_started_at)}`),
      b.incomplete_pipelines.length ? h("div", { class: "detail" }, badge("incomplete"), ` ${b.incomplete_pipelines.join(", ")}`) : null,
      b.ci_runs.length ? h("div", { class: "detail" }, b.ci_runs.map((url, i) => [i ? " · " : "", external(url, `GitHub run ${i + 1}`)])) : h("div", { class: "detail" }, "no GitHub run recorded"),
    );
  const delta = (o) => {
    const change = (d.head.counts[o] ?? 0) - (d.base.counts[o] ?? 0);
    return `${o} ${change > 0 ? "+" : ""}${change}`;
  };
  const category = params.get("change") ?? "";
  const shown = d.changes.filter((c) => !category || c.category === category);
  return [
    ...header,
    h("div", { class: "toolbar" }, summaryButtons("/api/compare/summary", { base, head })),
    h("div", { class: "cards" }, side("Baseline", d.base), side("Comparison", d.head)),
    h("p", { class: "sub" }, `Result counts, comparison minus baseline (all runs of each build): ${OUTCOMES.map(delta).join(", ")}.`),
    d.notes.length ? h("div", { class: "notice", role: "note" }, d.notes.map((n) => h("p", {}, n))) : null,
    h("p", { class: "sub" }, `Compared suites: ${d.compared_contexts.join(", ") || "none"}`, d.only_in_base.length ? ` · only in the baseline: ${d.only_in_base.join(", ")}` : "", d.only_in_head.length ? ` · only in the comparison: ${d.only_in_head.join(", ")}` : ""),
    h(
      "nav",
      { class: "status-filter", "aria-label": "Change type" },
      h("a", { href: link("/compare", { base, head }), "aria-current": category ? null : "true" }, `All changes (${d.changes.length})`),
      Object.entries(d.category_counts).map(([c, n]) => h("a", { href: link("/compare", { base, head, change: c }), "aria-current": category === c ? "true" : null }, `${c} (${n})`)),
    ),
    table(
      ["Change", "Test", "Suite", "Baseline", "Comparison", { label: "Duration", num: true }],
      shown.map((c) =>
        h(
          "tr",
          {},
          h("td", {}, badge(c.category)),
          h("td", {}, h("a", { class: "key", href: drillLink("/test", { key: c.key }) }, c.key)),
          h("td", {}, c.context),
          h("td", {}, c.base_outcome ? badge(c.base_outcome) : "–"),
          h("td", {}, c.head_outcome ? badge(c.head_outcome) : "–"),
          h("td", { class: "num nowrap" }, c.base_seconds !== null || c.head_seconds !== null ? `${formatSeconds(c.base_seconds)} → ${formatSeconds(c.head_seconds)}` : "–"),
        ),
      ),
      d.comparable ? "No test changed between these builds." : "Nothing to compare: the builds share no suite.",
    ),
  ];
}

async function runsView() {
  const rows = await api(`/api/runs${apiQuery(RUN_FILTERS)}`);
  return [
    h("h1", {}, "Runs"),
    h("p", { class: "lead" }, `${rows.length} imported run(s), newest first.`),
    table(
      ["Run", "Pipeline / job", "Framework", "Browser", "Build", "Started", ...OUTCOMES.map((o) => ({ label: o, num: true })), { label: "Pass rate", num: true }],
      rows.map((r) => h("tr", {}, h("td", {}, h("a", { href: drillLink(`/run/${r.run_id}`) }, r.source)), h("td", {}, pipelineLabel(r.pipeline)), h("td", {}, r.context.framework ?? "–"), h("td", {}, r.context.browser ?? "–"), h("td", {}, r.context.build ?? "–"), h("td", { class: "nowrap" }, formatDate(r.started_at)), OUTCOMES.map((o) => h("td", { class: "num" }, r.counts[o])), h("td", { class: "num" }, r.pass_rate.text))),
      "No runs match these filters.",
    ),
  ];
}

async function runDetail(runId) {
  const d = await api(`/api/runs/${encodeURIComponent(runId)}`);
  const r = d.run;
  return [
    backToResults("Runs", "/runs"),
    crumbs([["Runs", link("/runs")], ...pipelineCrumbs(r.pipeline, null, null), [r.source, null]]),
    h("h1", {}, r.source),
    h("dl", { class: "meta" }, h("dt", {}, "Framework"), h("dd", {}, r.context.framework ?? "–"), h("dt", {}, "Environment"), h("dd", {}, r.context.environment ?? "–"), h("dt", {}, "Browser / platform"), h("dd", {}, `${r.context.browser ?? "–"} / ${r.context.platform ?? "–"}`), h("dt", {}, "Build"), h("dd", {}, r.context.build ?? "–"), h("dt", {}, "Pipeline / job"), h("dd", {}, pipelineLabel(r.pipeline)), h("dt", {}, "Started"), h("dd", {}, formatDate(r.started_at)), h("dt", {}, "Pass rate"), h("dd", {}, r.pass_rate.text)),
    table(EXECUTION_HEADERS, executionRows(d.executions), "This run has no results."),
  ];
}

/** "39238241112 / ui-chrome (attempt 2)", or a dash for a run that is not part of a pipeline. */
function pipelineLabel(p) {
  if (!p) return "–";
  return `${p.pipeline_id} / ${p.job}${p.attempt > 1 ? ` (attempt ${p.attempt})` : ""}`;
}

const STATUS_ORDER = ["incomplete", "failure", "cancelled", "success", "complete"];

/** An external link (GitHub run or commit): opens in a new tab, never passes the referrer. */
function external(href, text) {
  return h("a", { href, target: "_blank", rel: "noopener noreferrer" }, text);
}

function attemptsTable(p) {
  if (p.attempts.length < 2) return null;
  return h(
    "div",
    {},
    h("h3", {}, `Attempts (${p.attempts.length})`),
    table(
      ["Attempt", "CI conclusion", "Collection", { label: "Runs", num: true }, { label: "Results", num: true }, "Collected", "Problems"],
      p.attempts.map((a) => h("tr", {}, h("td", {}, String(a.attempt)), h("td", {}, badge(a.conclusion)), h("td", {}, badge(a.state)), h("td", { class: "num" }, String(a.runs)), h("td", { class: "num" }, String(a.results)), h("td", { class: "nowrap" }, formatDate(a.collected_at)), h("td", {}, a.problems.join("; ") || "–"))),
      "",
    ),
  );
}

function pipelineDetails(p, open) {
  const title = [p.repository ? p.repository.split("/")[1] : p.pipeline_id, p.workflow, p.run_number ? `#${p.run_number}` : null].filter(Boolean).join(" · ");
  return h(
    "details",
    { class: "pipeline", open: open ? "" : null },
    h(
      "summary",
      {},
      h("span", { class: "pipeline-title" }, title),
      " ",
      badge(p.status),
      h("span", { class: "sub" }, [p.branch ? `branch ${p.branch}` : null, p.commit ? `commit ${p.commit}` : null, formatDate(p.started_at), `pass rate ${p.pass_rate.text}`].filter(Boolean).join(" · ")),
    ),
    h(
      "p",
      { class: "links" },
      `Pipeline ${p.pipeline_id}`,
      p.conclusion ? ` · CI concluded: ${p.conclusion}` : "",
      p.url ? [" · ", external(p.url, "Open the workflow run on GitHub")] : null,
      p.commit_url ? [" · ", external(p.commit_url, "Open the commit")] : null,
    ),
    p.problems.length ? h("ul", { class: "reasons" }, p.problems.map((problem) => h("li", {}, problem))) : null,
    table(
      ["Job", "Attempt", "Started", { label: "Runs", num: true }, ...OUTCOMES.map((o) => ({ label: o, num: true })), { label: "Pass rate", num: true }],
      [
        ...p.jobs.map((j) =>
          h(
            "tr",
            {},
            h("td", {}, j.run_ids.length === 1 ? h("a", { href: drillLink(`/run/${j.run_ids[0]}`) }, j.name) : j.name, j.expected ? null : h("span", { class: "sub" }, "not an expected job")),
            h("td", {}, String(j.attempt), j.superseded_runs ? h("span", { class: "sub" }, `${j.superseded_runs} earlier run(s) replaced`) : null),
            h("td", { class: "nowrap" }, formatDate(j.started_at)),
            h("td", { class: "num" }, String(j.run_ids.length)),
            OUTCOMES.map((o) => h("td", { class: "num" }, j.counts[o])),
            h("td", { class: "num" }, j.pass_rate.text),
          ),
        ),
        ...p.missing.map((name) => h("tr", { class: "missing" }, h("td", {}, name), h("td", { colspan: String(4 + OUTCOMES.length) }, "missing: no results reported"))),
      ],
      "No job reported results.",
    ),
    attemptsTable(p),
  );
}

async function pipelinesView() {
  const params = route().params;
  const jobs = params.get("jobs") ?? "";
  const status = params.get("status") ?? "";
  const workflow = params.get("workflow") ?? "";
  const focus = params.get("pipeline") ?? "";
  const d = await api(`/api/pipelines${apiQuery(RUN_FILTERS, { jobs, status, workflow, pipeline: focus })}`);
  const jobsInput = h("input", { id: "expected-jobs", type: "text", value: jobs, placeholder: "api, ui-chrome, ui-firefox", size: "40" });
  jobsInput.addEventListener("change", () => (location.hash = link("/pipelines", { jobs: jobsInput.value.trim(), status, workflow })));
  const workflowSelect = h("select", { id: "workflow" }, h("option", { value: "" }, "All"), d.workflows.map((w) => h("option", { value: w }, w)));
  workflowSelect.value = workflow;
  workflowSelect.addEventListener("change", () => (location.hash = link("/pipelines", { jobs, status, workflow: workflowSelect.value })));
  const statuses = [...STATUS_ORDER.filter((s) => s in d.status_counts), ...Object.keys(d.status_counts).filter((s) => !STATUS_ORDER.includes(s))];
  const total = Object.values(d.status_counts).reduce((a, b) => a + b, 0);
  const repository = params.get("repository") ?? "";
  return [
    focus || workflow ? crumbs([["Pipelines", link("/pipelines", { repository: null })], repository ? [repository, link("/pipelines", { pipeline: null, workflow: null })] : null, workflow ? [workflow, focus ? link("/pipelines", { pipeline: null }) : null] : null, focus ? [focus, null] : null]) : null,
    h("h1", {}, "Pipelines"),
    focus ? h("p", { class: "notice", role: "note" }, `Showing pipeline ${focus} only. `, h("a", { href: link("/pipelines", { workflow }) }, "Show every pipeline")) : null,
    h("p", { class: "lead" }, "Pipeline executions, newest first. Incomplete means jobs or reports are missing, whatever CI concluded; success, failure and cancelled are the CI's own conclusion of complete pipelines."),
    h(
      "div",
      { class: "toolbar" },
      h("label", { for: "workflow" }, "Workflow", workflowSelect),
      h("label", { for: "expected-jobs" }, "Expected jobs", jobsInput),
    ),
    h(
      "nav",
      { class: "status-filter", "aria-label": "Pipeline status" },
      h("a", { href: link("/pipelines", { jobs, workflow }), "aria-current": status ? null : "true" }, `All (${total})`),
      statuses.map((s) => h("a", { href: link("/pipelines", { jobs, workflow, status: s }), "aria-current": status === s ? "true" : null }, badge(s), ` ${d.status_counts[s]}`)),
    ),
    d.notes.length ? h("div", { class: "notice", role: "note" }, d.notes.map((n) => h("p", {}, n))) : null,
    d.pipelines.length === 0
      ? h("p", { class: "empty" }, status || workflow ? "No pipeline matches this status or workflow; choose All to see every pipeline." : "No runs in scope belong to a pipeline (collect them with qi collect, or import with --pipeline and --job).")
      : d.pipelines.map((p, i) => pipelineDetails(p, i === 0 || Boolean(focus))),
  ];
}

async function collectionView() {
  const d = await api("/api/collection");
  const status = currentStatus ?? await api("/api/status");
  return [
    h("h1", {}, "Collection"),
    h("p", { class: "lead" }, `Operations view: dashboard snapshot refresh and CI collection freshness are separate from test execution quality. A repository is overdue when its latest collection record is older than ${d.expected_hours} hours.`),
    h("section", { class: "data-health", "aria-labelledby": "snapshot-health-title" },
      h("h2", { id: "snapshot-health-title" }, "Dashboard snapshot"),
      h("p", {}, badge(status.stale ? "stale" : "current"), " ", status.stale ? "Last good data is retained while refresh retries." : "The current snapshot loaded successfully."),
      h("dl", { class: "meta" },
        h("dt", {}, "Snapshot loaded"), h("dd", {}, formatDate(status.loaded_at)),
        h("dt", {}, "Last refresh check"), h("dd", {}, formatDate(status.last_check)),
        h("dt", {}, "Refresh interval"), h("dd", {}, status.refresh_seconds ? `every ${status.refresh_seconds} seconds` : "automatic refresh is disabled on the server"),
        h("dt", {}, "Latest collection record"), h("dd", {}, formatDate(status.latest_collection_at)),
      ),
      status.last_error ? h("p", { class: "notice", role: "status" }, `Last refresh error (${formatDate(status.last_error_at)}): ${status.last_error}`) : null,
      h("p", { class: "sub" }, "Refresh checks for updated dashboard source data. It does not start a CI collection workflow."),
    ),
    d.workflow_url ? h("p", {}, external(d.workflow_url, "Open the collection workflow on GitHub")) : null,
    d.notes.length ? h("div", { class: "notice", role: "note" }, d.notes.map((n) => h("p", {}, n))) : null,
    table(
      ["Repository", "Workflows", "Last collection", "Last complete collection", "Freshness", { label: "Pipelines (7 d)", num: true }, { label: "Complete", num: true }, { label: "Incomplete", num: true }, { label: "Results", num: true }, "CI conclusions"],
      d.repositories.map((r) =>
        h(
          "tr",
          { class: r.fresh ? null : "missing" },
          h("td", {}, h("a", { href: link("/pipelines", { repository: r.repository }) }, r.repository)),
          h("td", {}, r.workflows.join(", ")),
          h("td", { class: "nowrap" }, formatDate(r.last_collected_at)),
          h("td", { class: "nowrap" }, formatDate(r.last_complete_collection_at)),
          h("td", {}, badge(r.fresh ? "fresh" : "overdue"), h("span", { class: "sub" }, r.freshness)),
          h("td", { class: "num" }, String(r.pipelines)),
          h("td", { class: "num" }, String(r.complete)),
          h("td", { class: "num" }, String(r.incomplete)),
          h("td", { class: "num" }, String(r.results)),
          h("td", {}, Object.entries(r.conclusions).map(([c, n]) => `${n} ${c}`).join(", ") || "–"),
        ),
      ),
      "No collection recorded.",
    ),
    d.repositories.some((r) => r.issues.length)
      ? [
          h("h2", {}, "Missing artifacts and ingestion problems (7 days)"),
          h("p", { class: "sub" }, "Each problem links to the pipeline here and to the run attempt on GitHub, where the job log tells why a report is missing."),
          h(
            "ul",
            { class: "reasons" },
            d.repositories.flatMap((r) =>
              r.issues.map((issue) =>
                h(
                  "li",
                  {},
                  `${r.repository}: ${issue.text} `,
                  h("a", { href: link("/pipelines", { repository: r.repository, status: "incomplete" }) }, `pipeline ${issue.pipeline_id} attempt ${issue.attempt}`),
                  issue.run_url ? [" · ", external(issue.run_url, "Open the run on GitHub")] : null,
                ),
              ),
            ),
          ),
        ]
      : h("p", {}, "No ingestion problems in the last 7 days."),
  ];
}

async function stabilityView() {
  const windowSize = route().params.get("window") ?? "10";
  const d = await api(`/api/stability${apiQuery(RUN_FILTERS, { window: windowSize })}`);
  const windowSelect = h("select", { id: "window" }, ["5", "10", "20", "50"].map((v) => h("option", { value: v }, `last ${v} verdicts`)));
  windowSelect.value = windowSize;
  windowSelect.addEventListener("change", () => (location.hash = link("/stability", { window: windowSelect.value })));
  const order = ["consistently failing", "new failure", "flaky candidate", "recovered", "insufficient data", "stable"];
  return [
    h("h1", {}, "Stability"),
    h("p", { class: "lead" }, "Each test is judged per run context (framework, environment, browser, platform) from its last verdicts. The rules are in docs/metrics.md; every row lists the evidence."),
    h("div", { class: "toolbar" }, h("label", { for: "window" }, "Window", windowSelect)),
    h("div", { class: "cards" }, order.map((s) => countCard(s[0].toUpperCase() + s.slice(1), d.status_counts[s] ?? 0))),
    h("h2", {}, `Tests that need attention (${d.rows.length})`),
    h("p", { class: "sub" }, "A flaky candidate is a suspicion from the observations listed, not a proven root cause. Sort by failure rate (frequency), last failure (recency) or affected builds."),
    table(
      ["Test", "Context", "Status", { label: "Failure rate", num: true }, "Last failure", { label: "Affected builds", num: true }, "Evidence", "Runs", "Test case"],
      d.rows.map((r) =>
        h(
          "tr",
          {},
          h("td", {}, h("a", { class: "key", href: drillLink("/test", { key: r.key }) }, r.key), r.last_failure ? h("span", { class: "sub" }, `last failure: ${r.last_failure.split("\n")[0].slice(0, 160)}`) : null),
          h("td", {}, r.context),
          h("td", {}, badge(r.status), r.status === "flaky candidate" ? h("span", { class: "sub" }, "suspected") : null),
          h("td", { class: "num" }, r.failure_rate.text),
          h("td", { class: "nowrap" }, formatDate(r.last_failed_at)),
          h("td", { class: "num" }, String(r.affected_builds.length), r.affected_builds.length ? h("span", { class: "sub" }, r.affected_builds.join(", ")) : null),
          h("td", {}, h("ul", { class: "reasons" }, r.reasons.map((reason) => h("li", {}, reason)))),
          h("td", {}, r.last_failing_run_id ? h("a", { href: drillLink(`/run/${r.last_failing_run_id}`) }, "last failing") : "–", r.last_passing_run_id ? [" · ", h("a", { href: drillLink(`/run/${r.last_passing_run_id}`) }, "last passing")] : null),
          h("td", {}, r.test_cases.join(", ") || "–"),
        ),
      ),
      "No test needs attention in this window: every test is stable or has too little history.",
    ),
    h("h2", {}, `Recurring failures (${d.recurring_failures.length})`),
    h("p", { class: "sub" }, "Ranked by runs in the 7 days before the newest run, then all runs, then the latest occurrence (docs/metrics.md)."),
    table(
      ["Failure signature", { label: "Last 7 days", num: true }, { label: "Runs", num: true }, { label: "Times", num: true }, "Last seen", "Tests", "Evidence"],
      d.recurring_failures.map((f) => h("tr", {},
        h("td", { class: "key" }, f.signature),
        h("td", { class: "num" }, f.recent_runs),
        h("td", { class: "num" }, f.runs),
        h("td", { class: "num" }, f.occurrences),
        h("td", { class: "nowrap" }, f.last_seen ? formatDate(f.last_seen) : "not recorded"),
        h("td", {}, f.tests.map((t) => h("span", { class: "sub key" }, t))),
        h("td", {}, f.run_ids.map((id, i) => [i ? " · " : null, h("a", { href: drillLink(`/run/${id}`) }, i ? `run ${i + 1}` : "newest run")]), f.runs > f.run_ids.length ? ` (${f.run_ids.length} of ${f.runs})` : null),
      )),
      "No failure cause appeared in more than one run.",
    ),
    h("h2", {}, `Duration regressions (${d.duration_regressions.length})`),
    table(
      ["Test", "Context", { label: "Baseline", num: true }, { label: "Latest", num: true }],
      d.duration_regressions.map((r) => h("tr", {}, h("td", {}, h("a", { class: "key", href: drillLink("/test", { key: r.key }) }, r.key)), h("td", {}, r.context), h("td", { class: "num" }, `${formatSeconds(r.baseline_seconds)} (${r.baseline_runs} runs)`), h("td", { class: "num" }, formatSeconds(r.latest_seconds)))),
      "No test got clearly slower in two runs in a row.",
    ),
    h("h2", {}, "Runs per context (oldest to newest)"),
    Object.keys(d.trends).length
      ? h(
          "div",
          { class: "cards" },
          Object.entries(d.trends).map(([context, points]) =>
            h(
              "div",
              { class: "card" },
              h("div", { class: "label" }, context),
              h(
                "ol",
                { class: "strip", "aria-label": `${points.length} runs` },
                points.map((p) => h("li", {}, h("a", { href: drillLink(`/run/${p.run_id}`), class: p.failed ? "bad" : "good", title: `${formatDate(p.started_at)} · build ${p.build ?? "–"} · ${p.pass_rate.text}` }, h("span", { class: "sr" }, `${formatDate(p.started_at)}: ${p.pass_rate.text}`)))),
              ),
              h("div", { class: "detail" }, `${points.filter((p) => p.failed).length} of ${points.length} runs with failures`),
            ),
          ),
        )
      : h("p", { class: "empty" }, "No runs in this scope."),
  ];
}

// ---- charts (inline SVG, no library; every chart also has its numbers as a table) ---------

const SVG_NS = "http://www.w3.org/2000/svg";
const CHART = { width: 640, height: 220, left: 46, right: 26, top: 12, bottom: 30 };

/** Create an SVG element with attributes and children. */
function s(tag, attrs = {}, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [name, value] of Object.entries(attrs)) el.setAttribute(name, String(value));
  for (const child of children.flat()) if (child) el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return el;
}

/** Axes, grid lines and x labels shared by both chart types; returns the plotting helpers. */
function frame(labels, max, unit) {
  const w = CHART.width - CHART.left - CHART.right;
  const hgt = CHART.height - CHART.top - CHART.bottom;
  const x = (i) => CHART.left + (labels.length === 1 ? w / 2 : (i * w) / (labels.length - 1));
  const y = (v) => CHART.top + hgt - (max === 0 ? 0 : (v / max) * hgt);
  const parts = [];
  for (const tick of [0, max / 2, max]) {
    parts.push(s("line", { class: "grid", x1: CHART.left, x2: CHART.width - CHART.right, y1: y(tick), y2: y(tick) }));
    parts.push(s("text", { class: "axis", x: CHART.left - 6, y: y(tick) + 4, "text-anchor": "end" }, `${+tick.toFixed(1)}${unit}`));
  }
  const step = Math.max(1, Math.ceil(labels.length / 8));
  labels.forEach((label, i) => {
    if (i % step === 0 || i === labels.length - 1) parts.push(s("text", { class: "axis", x: x(i), y: CHART.height - 10, "text-anchor": "middle" }, label));
  });
  return { x, y, w, parts };
}

/** Stacked bars: one bar per label, one segment per series ({name, cls, values}). */
/**
 * Stacked bars. With ``hrefs`` (one per label) every bar is a link, reachable with Tab, whose
 * accessible name lists that bar's numbers (e.g. to the runs of that day).
 */
function stackedBars(labels, series, unit = "", hrefs = null, axisLabels = labels) {
  const totals = labels.map((_, i) => series.reduce((sum, item) => sum + (item.values[i] ?? 0), 0));
  const max = Math.max(1, ...totals);
  const f = frame(axisLabels, max, unit);
  const barWidth = Math.max(4, Math.min(36, (f.w / labels.length) * 0.6));
  const bars = [];
  labels.forEach((label, i) => {
    let base = 0;
    const pieces = [];
    for (const item of series) {
      const value = item.values[i] ?? 0;
      if (value > 0) {
        const top = f.y(base + value);
        pieces.push(s("rect", { class: item.cls, x: f.x(i) - barWidth / 2, y: top, width: barWidth, height: f.y(base) - top }, s("title", {}, `${label}: ${item.name} ${value}`)));
      }
      base += value;
    }
    if (hrefs && pieces.length) {
      const summary = `${label}: ${series.map((item) => `${item.values[i] ?? 0} ${item.name}`).join(", ")}. Open the runs.`;
      bars.push(s("a", { href: hrefs[i], class: "bar-link", "aria-label": summary }, s("title", {}, summary), pieces));
    } else {
      bars.push(...pieces);
    }
  });
  const attrs = { viewBox: `0 0 ${CHART.width} ${CHART.height}`, class: "chart-svg" };
  return s("svg", hrefs ? { ...attrs, role: "group", "aria-label": "Bars, one link per day" } : { ...attrs, "aria-hidden": "true" }, f.parts, bars);
}

/** Lines: one per series ({name, cls, values}); a null value leaves a gap. */
function lineChart(labels, series, { max = null, unit = "" } = {}) {
  const top = max ?? Math.max(1, ...series.flatMap((item) => item.values.filter((v) => v !== null)));
  const f = frame(labels, top, unit);
  const drawn = [];
  for (const item of series) {
    let path = "";
    item.values.forEach((value, i) => {
      if (value === null) return;
      path += `${path && item.values[i - 1] !== null ? "L" : "M"}${f.x(i)},${f.y(value)}`;
      drawn.push(s("circle", { class: `dot ${item.cls}`, cx: f.x(i), cy: f.y(value), r: 3 }, s("title", {}, `${labels[i]}: ${item.name} ${value}${unit}`)));
    });
    drawn.unshift(s("path", { class: `line ${item.cls}`, d: path }));
  }
  return s("svg", { viewBox: `0 0 ${CHART.width} ${CHART.height}`, class: "chart-svg", "aria-hidden": "true" }, f.parts, drawn);
}

/** A chart with title, legend (the drawn series), a summary for screen readers and its data as a table. */
function chartFigure(title, svg, series, labels, summary, format = (v) => v, drawn = series) {
  return h(
    "figure",
    { class: "chart", role: "group", "aria-label": `${title}. ${summary}` },
    h("figcaption", {}, h("strong", {}, title), h("span", { class: "sub" }, summary)),
    h("ul", { class: "legend" }, drawn.map((item) => h("li", {}, h("span", { class: `swatch ${item.cls}` }), item.name))),
    svg,
    h(
      "details",
      {},
      h("summary", {}, "Show the numbers"),
      table(
        ["", ...series.map((item) => ({ label: item.name, num: true }))],
        labels.map((label, i) => h("tr", {}, h("td", { class: "nowrap" }, label), series.map((item) => h("td", { class: "num" }, item.values[i] === null ? "–" : format(item.values[i]))))),
        "No data.",
        { tools: false, pageSize: 1000 },
      ),
    ),
  );
}

const shortDay = (iso) => iso.slice(5);

// The release gate on each day's snapshot and the days it changed (docs/quality-gates.md, Gate history)
function gateHistory(g) {
  const dayRuns = (day) => link("/runs", { since: day, until: day });
  if (!g.gate_name) return [h("h2", {}, "Release gate over time"), h("p", { class: "empty" }, g.notes.join(" "))];
  return [
    h("h2", {}, `Release gate over time: "${g.gate_name}"`),
    h("p", { class: "sub" }, g.notes.join(" ")),
    h("h3", {}, `Days the verdict or its reasons changed (${g.changes.length})`),
    table(
      ["Day", "Verdict", "Started failing", "Stopped failing", "Evidence"],
      g.changes.map((c) => h("tr", {},
        h("td", { class: "nowrap" }, c.day),
        h("td", { class: "nowrap" }, c.previous === c.status ? `${c.status} (reasons changed)` : `${c.previous} → ${c.status}`),
        h("td", {}, c.started_failing.join(", ") || "–"),
        h("td", {}, c.stopped_failing.join(", ") || "–"),
        h("td", {}, h("a", { href: dayRuns(c.day) }, "runs of that day")),
      )),
      g.days.length ? "The verdict and its failing rules did not change on any listed day." : "No dated runs in this scope.",
    ),
    h("details", {},
      h("summary", {}, `Verdict per day (${g.days.length} days)`),
      table(
        ["Day", "Verdict", "Failing rules", { label: "Results", num: true }, "Newest run"],
        g.days.map((d) => h("tr", {},
          h("td", { class: "nowrap" }, d.day),
          h("td", {}, d.status),
          h("td", {}, [d.failed_rules.join(", "), d.input_problems.length ? ` (cannot decide: ${d.input_problems.join("; ")})` : ""].join("") || "–"),
          h("td", { class: "num" }, d.results),
          h("td", {}, d.latest_run_id ? h("a", { href: drillLink(`/run/${d.latest_run_id}`) }, "newest run") : "–"),
        )),
        "",
      ),
    ),
  ];
}

// Each repository on the newest day against N days earlier (docs/metrics.md, Repository trends)
function repositoryTrends(t) {
  const side = (s) => (s ? [`${s.pass_rate.text} · ${s.failed} failed`, h("span", { class: "sub" }, `${s.day} · ${s.suites} suite(s) · `, s.latest_run_id ? h("a", { href: drillLink(`/run/${s.latest_run_id}`) }, "newest run") : "–")] : "no run yet");
  const tests = (keys) => (keys.length ? [keys.slice(0, 5).map((k, i) => [i ? ", " : null, h("a", { class: "key", href: drillLink("/test", { key: k }) }, k)]), keys.length > 5 ? ` and ${keys.length - 5} more` : null] : "–");
  return [
    h("h2", {}, t.day ? `Repositories: ${t.day} against ${t.days} days earlier` : "Repositories over time"),
    h("p", { class: "sub" }, `Repositories with new failures first, then the largest drop in pass rate. ${t.notes.join(" ")}`),
    table(
      ["Repository", `${t.days} days earlier`, "Newest day", "Started failing", "Stopped failing"],
      t.repositories.map((r) => h("tr", {},
        h("td", {}, h("a", { href: link("/trends", { repository: r.repository }) }, r.repository)),
        h("td", {}, side(r.before)),
        h("td", {}, side(r.now)),
        h("td", {}, tests(r.newly_failing)),
        h("td", {}, tests(r.fixed)),
      )),
      "No collected runs with a recorded repository in this scope.",
    ),
  ];
}

/** A status distribution with exact counts alongside an illustrative ring. */
function executionDistribution(d) {
  let offset = 0;
  const circles = OUTCOMES.map((outcome) => {
    const percent = d.percentages[outcome] ?? 0;
    const circle = s("circle", { class: `execution-slice ${outcome}`, cx: 60, cy: 60, r: 45, pathLength: 100, "stroke-dasharray": `${percent} ${100 - percent}`, "stroke-dashoffset": -offset });
    offset += percent;
    return circle;
  });
  return h("section", { class: "execution-panel", "aria-labelledby": "execution-status-title" },
    h("h2", { id: "execution-status-title" }, "Results by status"),
    s("svg", { viewBox: "0 0 120 120", class: "execution-donut", "aria-hidden": "true" },
      s("circle", { class: "execution-ring", cx: 60, cy: 60, r: 45 }), circles),
    table(["Status", { label: "Executions", num: true }, { label: "Percentage", num: true }],
      OUTCOMES.map((outcome) => h("tr", {}, h("th", { scope: "row" }, badge(outcome)), h("td", { class: "num" }, d.counts[outcome]), h("td", { class: "num" }, d.percentages[outcome] === null ? "n/a" : `${d.percentages[outcome].toFixed(1)} %`))),
      "No recorded results.", { tools: false }),
    h("p", { class: "sub" }, "Percentages use all recorded executions in scope, including skipped results. Coverage and release readiness remain separate."));
}

function executionTestLink(row) {
  const extra = { key: row.key, repository: row.repository, job: row.job,
    framework: row.context.framework, environment: row.context.environment, browser: row.context.browser };
  return h("div", {}, h("a", { class: "key", href: drillLink("/test", extra) }, row.name),
    h("span", { class: "sub" }, [row.repository || "Repository not recorded", row.suite || "Suite not recorded", row.job, row.context.framework, row.context.browser, row.context.environment, row.context.platform].filter(Boolean).join(" · ")));
}

function executionRanking(title, rows, kind) {
  const duration = kind === "duration";
  const headers = duration
    ? ["Test / execution context", { label: "Average (s)", num: true }, { label: "Maximum (s)", num: true }, { label: "Timed / total", num: true }]
    : ["Test / execution context", { label: kind === "failed" ? "Failures" : "Errors", num: true }, { label: "Executions", num: true }];
  const body = rows.map((row) => h("tr", {}, h("td", {}, executionTestLink(row)),
    duration ? [h("td", { class: "num" }, row.average_seconds.toFixed(3)), h("td", { class: "num" }, row.max_seconds.toFixed(3)), h("td", { class: "num" }, `${row.timed_executions} / ${row.executions}`)]
      : [h("td", { class: "num" }, row[kind === "failed" ? "failed" : "errors"]), h("td", { class: "num" }, row.executions)]));
  const data = table(headers, body, duration ? "No recorded durations in this scope." : "No matching results in this scope.",
    { tools: true, searchLabel: `Search ${title.toLowerCase()}`, searchPlaceholder: "Test or context", name: `execution-${kind}` });
  const scroll = data.querySelector(".table-wrap") ?? data;
  scroll.setAttribute("tabindex", "0");
  scroll.setAttribute("role", "region");
  scroll.setAttribute("aria-label", `${title} data; scroll horizontally on narrow screens`);
  return h("section", { class: "execution-panel execution-ranking" }, h("h2", {}, title),
    h("p", { class: "sub execution-scroll-hint" }, "Scroll the table horizontally to compare values."), data);
}

async function executionsView() {
  const params = route().params;
  const suite = params.get("suite");
  const limit = ["10", "25", "100"].includes(params.get("limit")) ? params.get("limit") : "10";
  const d = await api(`/api/executions${apiQuery(RUN_FILTERS, { suite, limit })}`);
  const suiteSelect = h("select", { id: "execution-suite" }, h("option", { value: "" }, "All suites"),
    d.suites.filter(Boolean).map((value) => h("option", { value }, value)));
  suiteSelect.value = suite ?? "";
  suiteSelect.addEventListener("change", () => (location.hash = link("/executions", { suite: suiteSelect.value || null, limit: route().params.get("limit") })));
  const limitSelect = h("select", { id: "execution-limit" }, ["10", "25", "100"].map((value) => h("option", { value }, `Top ${value}`)));
  limitSelect.value = limit;
  limitSelect.addEventListener("change", () => (location.hash = link("/executions", { suite: route().params.get("suite"), limit: limitSelect.value })));
  const duration = d.recorded_duration_seconds === null ? "Not recorded" : `${d.recorded_duration_seconds.toFixed(3)} s`;
  const cards = h("div", { class: "cards execution-cards" },
    countCard("Recorded executions", d.executions, null, `${d.unique_tests} test identities · ${d.runs} imported runs`, "All result records in the selected history, not the latest snapshot. A test identity is repository plus result key; parameter rows and browser runs are executions."),
    countCard("Recorded test duration", duration, null, `${d.timed_executions} of ${d.executions} executions have duration`, "Sum of recorded test durations. Missing durations are excluded; parallel tests overlap, so this is not elapsed CI time."),
    OUTCOMES.map((outcome) => countCard(outcome[0].toUpperCase() + outcome.slice(1), d.counts[outcome], null,
      d.percentages[outcome] === null ? "No executions" : `${d.percentages[outcome].toFixed(1)} % of recorded executions`)));
  const series = OUTCOMES.map((outcome) => ({ name: outcome, cls: `s-${outcome}`, values: d.daily.map((day) => day.counts[outcome]) }));
  const days = d.daily.map((day) => day.day);
  return [h("h1", {}, "Test execution dashboard"),
    h("p", { class: "lead" }, "Investigate recorded test executions across your repositories. Repository, framework, environment, browser, build, job and date filters apply; catalog-only filters do not change execution history."),
    h("div", { class: "toolbar" }, h("label", { for: "execution-suite" }, "Suite", suiteSelect), h("label", { for: "execution-limit" }, "Ranking size", limitSelect)), cards,
    h("p", { class: "sub" }, "Cancelled and in-progress are pipeline states, not imported test outcomes. ", h("a", { href: link("/pipelines") }, "Inspect pipeline status and missing reports"), "."),
    d.executions === 0 ? h("p", { class: "empty", role: "status" }, "No recorded executions match these filters. Clear filters or collect test reports.") : null,
    h("section", { class: "execution-panel" }, h("h2", {}, "Executions per recorded day"),
      chartFigure("Daily execution results", stackedBars(days, series, "", days.map((day) => link("/runs", { since: day, until: day })), days.map(shortDay)), series, days,
        `UTC run start dates; all imported executions, not daily snapshots. ${d.undated_executions} undated executions are excluded from this chart. Days without recorded runs are omitted; each bar opens that day's runs.`)),
    h("div", { class: "execution-grid" }, executionDistribution(d), executionRanking(`Top ${limit} longest-running tests`, d.slowest, "duration")),
    h("div", { class: "execution-grid execution-equal" }, executionRanking(`Top ${limit} test failures`, d.failures, "failed"), executionRanking(`Top ${limit} test errors`, d.errors, "error")),
    h("p", { class: "sub" }, "Rankings keep repository, job, suite and browser/environment/platform contexts separate. Average and maximum use recorded durations only; test links open history in the selected repository/job/browser scope. These findings do not change release gates.")];
}

async function trendsView() {
  const [d, g, rt] = await Promise.all([api(`/api/trends${apiQuery(FILTERS)}`), api(`/api/gate-history${apiQuery(FILTERS)}`), api(`/api/repository-trends${apiQuery(RUN_FILTERS)}`)]);
  const days = d.daily.map((p) => p.day);
  const labels = days.map(shortDay);
  const outcomeSeries = [
    { name: "passed", cls: "s-passed", values: d.daily.map((p) => p.counts.passed) },
    { name: "failed", cls: "s-failed", values: d.daily.map((p) => p.counts.failed) },
    { name: "error", cls: "s-error", values: d.daily.map((p) => p.counts.error) },
    { name: "skipped", cls: "s-skipped", values: d.daily.map((p) => p.counts.skipped) },
  ];
  const statuses = ["passing", "failing", "not run", "skipped", "not automated"];
  const statusSeries = statuses.map((status) => ({ name: status, cls: `s-${status.replace(" ", "-")}`, values: d.daily.map((p) => p.requirement_status[status] ?? 0) }));
  const changes = d.daily.filter((p) => p.added.length || p.carried.length);
  const content = [
    h("h1", {}, "Trends"),
    h("p", { class: "lead" }, "Each day shows what a release decision would have seen at the end of it: the latest run of every framework, environment, browser and platform. Every chart has its numbers underneath."),
    d.notes.length ? h("div", { class: "notice", role: "note" }, h("strong", {}, "Read with care: "), h("ul", {}, d.notes.map((n) => h("li", {}, n)))) : null,
  ];
  if (!d.daily.length) {
    content.push(h("p", { class: "empty" }, "No dated runs in this scope, so there is no trend to draw."));
  } else {
    content.push(
      h("h2", {}, "Executions per day"),
      h(
        "div",
        { class: "charts" },
        chartFigure("Test results", stackedBars(labels, outcomeSeries, "", days.map((day) => link("/runs", { since: day, until: day }))), outcomeSeries, days, `${days.length} days from ${days[0]} to ${days.at(-1)}`),
        chartFigure("Execution pass rate", lineChart(labels, [{ name: "pass rate", cls: "s-rate", values: d.daily.map((p) => p.pass_rate.percent) }], { max: 100, unit: "%" }), [{ name: "pass rate", cls: "s-rate", values: d.daily.map((p) => p.pass_rate.text) }], days, "passed of passed, failed and error; skipped not counted"),
        chartFigure("Test duration", lineChart(labels, [{ name: "seconds", cls: "s-duration", values: d.daily.map((p) => p.duration_seconds) }], { unit: "s" }), [{ name: "seconds", cls: "s-duration", values: d.daily.map((p) => p.duration_seconds) }], days, "sum of the recorded test durations in the day's snapshot", (v) => v.toFixed(1)),
        chartFigure("Requirements by execution status", stackedBars(labels, statusSeries), statusSeries, days, "current catalog applied to each day's snapshot"),
      ),
      changes.length
        ? h("div", {}, h("h2", {}, "Days that are not comparable with the day before"), table(["Day", "New suites", "Carried over from earlier days"], changes.map((p) => h("tr", {}, h("td", { class: "nowrap" }, p.day), h("td", {}, p.added.join(", ") || "–"), h("td", {}, p.carried.join(", ") || "–"))), ""))
        : null,
    );
  }
  content.push(...gateHistory(g));
  content.push(...repositoryTrends(rt));
  content.push(h("h2", {}, "Runs per context"));
  const contexts = Object.entries(d.runs);
  content.push(
    contexts.length
      ? h(
          "div",
          { class: "charts" },
          contexts.map(([context, runs]) => {
            const runLabels = runs.map((r) => (r.started_at ? shortDay(r.started_at.slice(0, 10)) : "–"));
            const series = [{ name: "failed + error", cls: "s-failed", values: runs.map((r) => r.counts.failed + r.counts.error) }, { name: "duration (s)", cls: "s-duration", values: runs.map((r) => r.duration_seconds) }];
            return chartFigure(context, lineChart(runLabels, [series[1]], { unit: "s" }), series, runs.map((r) => `${r.started_at ? r.started_at.slice(0, 16).replace("T", " ") : "undated"} · ${r.build ?? "–"}`), `${runs.length} run(s); duration per run, failures in the table`, (v) => (Number.isInteger(v) ? v : v.toFixed(1)), [series[1]]);
          }),
        )
      : h("p", { class: "empty" }, "No runs in this scope."),
  );
  content.push(h("h2", {}, "Coverage over time"));
  if (d.coverage.length >= 2) {
    const covLabels = d.coverage.map((c) => shortDay(c.taken_at.slice(0, 10)));
    const covSeries = [
      { name: "requirement coverage", cls: "s-rate", values: d.coverage.map((c) => c.requirement_coverage.percent) },
      { name: "automation coverage", cls: "s-duration", values: d.coverage.map((c) => c.automation_coverage.percent) },
      { name: "automated requirement coverage", cls: "s-passed", values: d.coverage.map((c) => c.automated_requirement_coverage.percent) },
    ];
    content.push(chartFigure("Coverage snapshots", lineChart(covLabels, covSeries, { max: 100, unit: "%" }), covSeries, d.coverage.map((c) => c.taken_at.slice(0, 16).replace("T", " ")), "recorded when the catalog changed"));
  } else {
    content.push(
      table(
        ["Recorded", "Catalog", { label: "Requirements", num: true }, "Requirement coverage", "Automation coverage", "Automated requirement coverage"],
        d.coverage.map((c) => h("tr", {}, h("td", { class: "nowrap" }, formatDate(c.taken_at)), h("td", {}, c.catalog), h("td", { class: "num" }, c.requirements), h("td", {}, c.requirement_coverage.text), h("td", {}, c.automation_coverage.text), h("td", {}, c.automated_requirement_coverage.text))),
        "No coverage snapshot recorded yet.",
      ),
    );
  }
  return content;
}

// ---- main loop -------------------------------------------------------------------------


// ---- M12: search, needs attention, breadcrumbs, summaries ----------------------------------------

const KIND_TITLES = { repository: "Repositories", workflow: "Workflows", pipeline: "Pipelines", test: "Tests", requirement: "Requirements", failure: "Failure messages" };

/** The text with every query word marked, built from text nodes only (never HTML). */
function highlight(text, words) {
  let lower = "";
  const originalStarts = [];
  const originalEnds = [];
  let offset = 0;
  for (const character of text) {
    const folded = character.toLowerCase();
    lower += folded;
    for (let i = 0; i < folded.length; i += 1) {
      originalStarts.push(offset);
      originalEnds.push(offset + character.length);
    }
    offset += character.length;
  }
  const marks = [];
  for (const word of words) {
    let from = 0;
    while (word && (from = lower.indexOf(word, from)) !== -1) {
      const start = originalStarts[from];
      const end = originalEnds[from + word.length - 1];
      if (start !== undefined && end !== undefined) marks.push([start, end]);
      from += word.length;
    }
  }
  marks.sort((a, b) => a[0] - b[0]);
  const parts = [];
  let at = 0;
  for (const [start, end] of marks) {
    if (start < at) continue; // overlapping words: the first one wins
    if (start > at) parts.push(text.slice(at, start));
    parts.push(h("mark", {}, text.slice(start, end)));
    at = end;
  }
  if (at < text.length) parts.push(text.slice(at));
  return parts;
}

/** Breadcrumb navigation: [label, href] pairs, the last one is the current page (no link). */
function crumbs(items) {
  const shown = items.filter(Boolean);
  return h(
    "nav",
    { class: "crumbs", "aria-label": "Breadcrumb" },
    h(
      "ol",
      {},
      shown.map(([label, href], i) =>
        h("li", {}, i === shown.length - 1 || !href ? h("span", { "aria-current": i === shown.length - 1 ? "page" : null }, label) : h("a", { href }, label)),
      ),
    ),
  );
}

/** The repository › workflow › pipeline › run chain of a run that came from a pipeline. */
function pipelineCrumbs(pipeline, workflow, runId, runLabel) {
  if (!pipeline) return [];
  return [
    pipeline.repository ? [pipeline.repository, link("/pipelines", { repository: pipeline.repository })] : null,
    workflow ? [workflow, link("/pipelines", { repository: pipeline.repository, workflow })] : null,
    [`${pipeline.pipeline_id} attempt ${pipeline.attempt}`, link("/pipelines", { repository: pipeline.repository, pipeline: pipeline.pipeline_id })],
    runId ? [runLabel ?? `job ${pipeline.job}`, link(`/run/${runId}`)] : null,
  ];
}

/** Two buttons that copy the summary the server builds (text and Markdown) for this view. */
function summaryButtons(endpoint, extra) {
  const make = (label, field) => {
    const button = h("button", { type: "button", class: "ghost copy" }, label);
    button.addEventListener("click", async () => {
      const shareLink = `${location.pathname}${location.search}${location.hash}`;
      try {
        const summary = await api(`${endpoint}${apiQuery(RUN_FILTERS, { ...extra, link: shareLink })}`);
        await navigator.clipboard.writeText(summary[field]);
        button.textContent = "Copied";
      } catch (error) {
        button.textContent = `Copy failed (${error.message})`;
      }
      setTimeout(() => (button.textContent = label), 2500);
    });
    return button;
  };
  return [make("Copy summary (text)", "text"), make("Copy summary (Markdown)", "markdown")];
}

let searchCount = 0;

async function searchView() {
  const q = route().params.get("q") ?? "";
  const input = h("input", { type: "search", id: "search-q", value: q, maxlength: "100", autocomplete: "off", "aria-describedby": "search-help" });
  const results = h("div", { id: "search-results", "aria-live": "polite" });
  const show = async (query) => {
    const current = ++searchCount;
    const trimmed = query.trim();
    if (trimmed.length < 2) {
      results.replaceChildren(h("p", { class: "empty" }, "Type at least two characters: a test name, a requirement id, a pipeline or GitHub run id, a repository, or words from a failure message."));
      return;
    }
    results.setAttribute("aria-busy", "true");
    let d;
    try {
      d = await api(`/api/search${apiQuery(RUN_FILTERS, { q: trimmed })}`);
    } catch (error) {
      if (current === searchCount) results.replaceChildren(h("p", { class: "error", role: "alert" }, `Search failed: ${error.message}`));
      return;
    } finally {
      if (current === searchCount) results.removeAttribute("aria-busy");
    }
    if (current !== searchCount) return; // an older answer arrived after a newer question
    const words = d.query.toLowerCase().split(/\s+/).filter(Boolean);
    const groups = Object.entries(d.groups).filter(([, hits]) => hits.length);
    results.replaceChildren(
      h("p", { class: "sub" }, `${d.total} match(es) for "${d.query}"${RUN_FILTERS.some((f) => route().params.get(f)) ? " in the filtered scope" : ""}.`),
      ...(groups.length === 0
        ? [h("p", { class: "empty" }, `Nothing matches "${d.query}". Every word must occur; try fewer words, part of a name, or remove filters above.`)]
        : groups.map(([kind, hits]) =>
            h(
              "section",
              { "aria-labelledby": `results-${kind}` },
              h("h2", { id: `results-${kind}` }, `${KIND_TITLES[kind] ?? kind} (${d.counts[kind]}${d.counts[kind] > hits.length ? `, showing ${hits.length}` : ""})`),
              h(
                "ul",
                { class: "hits" },
                hits.map((hit) =>
                  h(
                    "li",
                    {},
                    h("a", { href: drillLink(hit.route, hit.params), class: "key" }, highlight(hit.identifier, words)),
                    hit.title && hit.title !== hit.identifier ? h("span", { class: "sub" }, highlight(hit.title, words)) : null,
                    h("span", { class: "sub" }, [hit.repositories.length ? hit.repositories.join(", ") : null, hit.last_seen ? `last seen ${formatDate(hit.last_seen)}` : null].filter(Boolean).join(" · ")),
                    hit.url ? external(hit.url, "Open the run on GitHub") : null,
                  ),
                ),
              ),
            ),
          )),
    );
  };
  let timer = null;
  input.addEventListener("input", () => {
    clearTimeout(timer);
    timer = setTimeout(() => {
      // The address follows the query (shareable, back button), without re-rendering the page
      history.replaceState(null, "", link("/search", { q: input.value.trim() }));
      show(input.value);
    }, 250);
  });
  show(q);
  return [
    h("h1", {}, "Search"),
    h("p", { class: "lead", id: "search-help" }, "Tests, failure messages, requirements, pipelines and GitHub run ids, workflows and repositories. Every word must occur; the repository and date filters above apply."),
    h("div", { class: "toolbar" }, h("label", { for: "search-q" }, "Search for", input)),
    results,
  ];
}

const STATE_ORDER = ["open", "suspected", "unknown", "resolved"];
const ATTENTION_TYPES = ["newly failing", "incomplete pipeline", "critical gap", "recurring failure", "duration regression", "flaky candidate", "overdue collection"];

async function attentionView() {
  const params = route().params;
  const state = params.get("state") ?? "";
  const kind = params.get("kind") ?? "";
  const d = await api(`/api/attention${apiQuery(FILTERS, { kind })}`);
  const shown = d.findings.filter((f) => !state || f.state === state);
  const kindSelect = h("select", { id: "finding-kind" }, h("option", { value: "" }, "All finding types"), ATTENTION_TYPES.map((value) => h("option", { value }, value)));
  kindSelect.value = kind;
  kindSelect.addEventListener("change", () => (location.hash = link("/attention", { state, kind: kindSelect.value })));
  const groups = [
    { title: "Investigate now", states: ["open"], description: "The latest evidence still shows the listed problem." },
    { title: "Monitor", states: ["suspected", "unknown"], description: "The evidence is mixed or not enough to resolve the finding." },
    { title: "Resolved", states: ["resolved"], description: "Later evidence shows the condition gone; retained as history." },
  ];
  const findingRows = (findings) => findings.map((f) => {
    const target = link(f.route, { ...f.params, from: location.hash });
    const copy = h("button", { type: "button", class: "ghost copy-link", "aria-label": `Copy link for ${f.title}` }, "Copy link");
    copy.addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(`${location.origin}${location.pathname}${target}`);
        copy.textContent = "Copied";
      } catch (_) {
        copy.textContent = "Copy unavailable";
      }
      setTimeout(() => (copy.textContent = "Copy link"), 2200);
    });
    return h("tr", {},
      h("td", {}, badge(f.state)),
      h("td", {}, f.kind),
      h("td", {}, h("a", { class: "key", href: target }, f.title)),
      h("td", {}, f.why),
      h("td", { class: "num" }, String(f.evidence), h("span", { class: "sub" }, f.evidence_label)),
      h("td", { class: "nowrap" }, f.first_seen ? formatDate(f.first_seen) : "not recorded"),
      h("td", { class: "nowrap" }, f.last_seen ? formatDate(f.last_seen) : "not recorded"),
      h("td", {}, f.repository ?? "not recorded"),
      h("td", {}, f.url ? external(f.url, "GitHub run") : "not available"),
      h("td", {}, copy),
    );
  });
  return [
    h("h1", {}, "Needs attention"),
    h("p", { class: "lead" }, "Findings from the existing attention analysis, grouped by its documented evidence state. Open findings are shown first; suspected and unknown findings need review; resolved findings remain available as history."),
    h("nav", { class: "status-filter", "aria-label": "Finding state" },
      h("a", { href: link("/attention", { state: null, kind }), "aria-current": state ? null : "true" }, `All (${d.total})`),
      STATE_ORDER.filter((s) => d.states[s]).map((s) => h("a", { href: link("/attention", { state: s, kind }), "aria-current": state === s ? "true" : null }, badge(s), ` ${d.states[s]}`)),
    ),
    h("div", { class: "toolbar" }, h("label", { for: "finding-kind" }, "Finding type", kindSelect)),
    d.notes.length ? h("div", { class: "notice", role: "note" }, d.notes.map((n) => h("p", {}, n))) : null,
    d.total === 0
      ? h("p", { class: "empty" }, "No findings were returned for this scope.")
      : shown.length === 0
        ? h("p", { class: "empty" }, "No findings match these state and type filters.")
        : groups.map((group) => {
            const findings = shown.filter((finding) => group.states.includes(finding.state));
            return findings.length ? h("details", { class: "action-group", open: group.states.includes("open") || group.states.includes(state) ? "" : null },
              h("summary", {}, `${group.title} (${findings.length})`),
              h("p", { class: "sub" }, group.description),
              table(
                ["State", "Kind", "Affected entity", "Observed reason", { label: "Evidence", num: true }, "First seen", "Last seen", "Repository", "GitHub evidence", "Actions"],
                findingRows(findings),
                `No ${group.title.toLowerCase()} findings in this filtered view.`,
                { tools: true, name: `attention-${group.states.join("-")}` },
              ),
            ) : null;
          }),
    d.shown < d.total ? h("p", { class: "sub" }, `Showing the first ${d.shown} of ${d.total} findings; narrow the scope with the filters above.`) : null,
  ];
}

/** Two executions of a test side by side: outcome, build, duration, retries, failure, evidence. */
function executionComparison(executions) {
  if (executions.length < 2) return null;
  const label = (e, i) => `${i === 0 ? "latest · " : ""}${formatDate(e.started_at)} · build ${e.context.build ?? "–"} · ${e.outcome}`;
  const pick = (id, chosen) => {
    const select = h("select", { id }, executions.map((e, i) => h("option", { value: String(i) }, label(e, i))));
    select.value = String(chosen);
    return select;
  };
  const left = pick("execution-a", 1);
  const right = pick("execution-b", 0);
  const body = h("tbody");
  const row = (name, a, b) => h("tr", {}, h("th", { scope: "row" }, name), h("td", {}, a), h("td", {}, b));
  const draw = () => {
    const a = executions[Number(left.value)];
    const b = executions[Number(right.value)];
    const failure = (e) => (e.failure ? (e.failure.message || e.failure.type || "").split("\n")[0].slice(0, 200) : "none recorded");
    const where = (e) => (e.pipeline ? `${e.pipeline.pipeline_id} attempt ${e.pipeline.attempt} / ${e.pipeline.job}` : "not part of a pipeline");
    body.replaceChildren(
      row("Outcome", badge(a.outcome), badge(b.outcome)),
      row("Started", formatDate(a.started_at), formatDate(b.started_at)),
      row("Build", a.context.build ?? "not recorded", b.context.build ?? "not recorded"),
      row("Context", [a.context.framework, a.context.environment, a.context.browser, a.context.platform].map((v) => v ?? "–").join(" / "), [b.context.framework, b.context.environment, b.context.browser, b.context.platform].map((v) => v ?? "–").join(" / ")),
      row("Duration", a.duration_seconds === null ? "not recorded" : formatSeconds(a.duration_seconds), b.duration_seconds === null ? "not recorded" : formatSeconds(b.duration_seconds)),
      row("Retries", String(a.retries), String(b.retries)),
      row("Failure", failure(a), failure(b)),
      row("Pipeline", where(a), where(b)),
      row("Evidence", a.ci_url ? external(a.ci_url, "GitHub run") : h("a", { href: drillLink(`/run/${a.run_id}`) }, "run"), b.ci_url ? external(b.ci_url, "GitHub run") : h("a", { href: drillLink(`/run/${b.run_id}`) }, "run")),
    );
  };
  left.addEventListener("change", draw);
  right.addEventListener("change", draw);
  draw();
  return h(
    "section",
    { "aria-labelledby": "compare-executions-title" },
    h("h2", { id: "compare-executions-title" }, "Compare two executions"),
    h("div", { class: "toolbar" }, h("label", { for: "execution-a" }, "Execution A", left), h("label", { for: "execution-b" }, "Execution B", right)),
    h("div", { class: "table-wrap" }, h("table", { class: "pair" }, h("thead", {}, h("tr", {}, h("th", { scope: "col" }, ""), h("th", { scope: "col" }, "A"), h("th", { scope: "col" }, "B"))), body)),
  );
}

const VIEWS = {
  "": overview,
  search: searchView,
  attention: attentionView,
  requirements: requirementsView,
  requirement: (parts) => requirementDetail(parts[1]),
  tests: testsView,
  test: testHistory,
  runs: runsView,
  run: (parts) => runDetail(parts[1]),
  pipelines: pipelinesView,
  collection: collectionView,
  compare: compareView,
  stability: stabilityView,
  trends: trendsView,
  executions: executionsView,
};

// Each render gets a number; only the latest may write to the page. Without this, a slow
// response for an older address (e.g. the first of two quickly changed filters) arrives last
// and shows data that no longer matches the address (seen in CI).
let renderCount = 0;
let shownPath = null; // the page last shown, to move focus only when the page changes

async function render() {
  const current = ++renderCount;
  const { parts } = route();
  const name = parts[0] ?? "";
  const section = { requirement: "requirements", test: "tests", run: "runs", "": "overview" }[name] ?? name;
  for (const a of document.querySelectorAll(".section-nav a[data-nav]")) {
    // Section links keep the active filters, like every other link on the page
    a.setAttribute("href", link(a.dataset.nav === "overview" ? "/" : `/${a.dataset.nav}`));
    if (a.dataset.nav === section) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  syncFilterForm();
  showActiveFilters();
  const handler = VIEWS[name];
  statusLine.textContent = "Loading…";
  view.setAttribute("aria-busy", "true");
  if (!view.childElementCount) {
    view.replaceChildren(h("div", { class: "skeleton-grid", "aria-hidden": "true" }, Array.from({ length: 4 }, () => h("div", { class: "skeleton" }))));
  }
  try {
    if (!handler) throw new Error("This page does not exist.");
    const content = await handler(parts);
    if (current !== renderCount) return; // a newer address is being rendered
    // Views may leave empty slots (cond ? node : null); they must not show up as "null"
    view.replaceChildren(...[content].flat(3).filter((node) => node != null));
    statusLine.textContent = "";
    view.removeAttribute("aria-busy");
    document.title = `${document.querySelector("#view h1")?.textContent ?? "Overview"} · Quality Intelligence`;
    const path = parts.join("/");
    if (shownPath !== null && path !== shownPath) {
      // Another page: put the focus on its heading (filters on the same page keep their focus)
      const heading = view.querySelector("h1");
      heading?.setAttribute("tabindex", "-1");
      heading?.focus();
    }
    shownPath = path;
  } catch (error) {
    if (current !== renderCount) return;
    view.removeAttribute("aria-busy");
    view.replaceChildren(h("div", { class: "error", role: "alert" }, h("strong", {}, "Could not load this view. "), error.message, " ", h("button", { type: "button", id: "retry" }, "Retry")));
    document.getElementById("retry").addEventListener("click", render);
    statusLine.textContent = "";
  }
}

window.addEventListener("hashchange", render);
// ---- data freshness and automatic refresh --------------------------------------------------
// The server reloads when its history or catalog change (docs/dashboard.md); the page asks
// /api/status regularly and re-renders the current view when the data version changes. The
// address, and with it every filter, stays as it is.

let dataVersion = null;
let statusTimer = null;
let currentStatus = null;
const freshLine = document.getElementById("data-fresh");
const staleNote = document.getElementById("data-stale");
const autoBox = document.getElementById("auto-refresh");
const refreshButton = document.getElementById("refresh-now");

function readPreference() {
  try {
    return localStorage.getItem("qi-auto-refresh") !== "off";
  } catch (_) {
    return true; // storage can be blocked; the default is on
  }
}

function writePreference(on) {
  try {
    localStorage.setItem("qi-auto-refresh", on ? "on" : "off");
  } catch (_) {
    /* not remembered, still applied */
  }
}

async function showDataSize() {
  const health = await api("/api/health");
  const commit = health.commit ? ` · commit ${health.commit.slice(0, 7)}` : "";
  document.getElementById("data-size").textContent = `${health.requirements} requirements · ${health.runs} runs · qi ${health.version}${commit}`;
  const notice = document.getElementById("catalog-notice");
  notice.textContent = health.catalog_notice ?? "";
  notice.hidden = !health.catalog_notice;
}

/** The freshness line as nodes: incomplete collections link to the pipelines they concern. */
function describe(status) {
  const parts = [`Data loaded ${formatDate(status.loaded_at)}`];
  if (status.latest_run_started_at) parts.push(`latest run ${formatDate(status.latest_run_started_at)}`);
  if (status.latest_collection_at) parts.push(`last collection ${formatDate(status.latest_collection_at)}`);
  if (status.incomplete_collections_7d) {
    parts.push(h("a", { href: link("/pipelines", { status: "incomplete" }) }, `${status.incomplete_collections_7d} incomplete collection(s) in 7 days`));
  }
  if (!status.refresh_seconds) parts.push("this server does not reload");
  return parts.flatMap((part, i) => (i ? [" · ", part] : [part]));
}

function showFreshness(status) {
  currentStatus = status;
  freshLine.replaceChildren(...describe(status));
}

let checking = false;

async function checkStatus(force = false) {
  if (checking) return; // one check at a time; a slow answer is not overtaken by another
  checking = true;
  const previous = [...freshLine.childNodes]; // the line may hold a link
  if (force) freshLine.textContent = "Checking for new data…"; // the content below stays
  try {
    await runCheck(force);
  } catch (error) {
    freshLine.replaceChildren(...previous);
    staleNote.hidden = false;
    staleNote.textContent = `Refresh failed (${error.message}); the page shows the data it loaded last.`;
  } finally {
    checking = false;
  }
}

async function runCheck(force) {
  let status;
  try {
    status = await api(`/api/status${force ? "?check=true" : ""}`);
  } catch (error) {
    staleNote.hidden = false;
    staleNote.textContent = `Data status unavailable (${error.message}); the page shows the data it loaded last.`;
    return;
  }
  showFreshness(status);
  staleNote.hidden = !status.stale;
  if (status.stale) {
    staleNote.replaceChildren(
      `The last refresh failed (${formatDate(status.last_error_at)}): ${status.last_error}. The figures shown are from ${formatDate(status.loaded_at)}; the dashboard keeps them and tries again on its own. `,
      "If it persists, check the ",
      h("a", { href: link("/collection") }, "Collection page"),
      " and the operations guide (docs/operations.md, Incidents).",
    );
  }
  if (dataVersion !== null && status.version !== dataVersion) {
    dataVersion = status.version;
    const scroll = window.scrollY;
    await showDataSize();
    await loadFacets();
    await render(); // same address, same filters, new data
    window.scrollTo(0, scroll); // where the reader was
  }
  dataVersion = status.version;
  scheduleChecks(status.refresh_seconds);
}

function scheduleChecks(serverSeconds) {
  if (statusTimer !== null) clearInterval(statusTimer);
  statusTimer = null;
  autoBox.disabled = !serverSeconds;
  if (autoBox.checked && serverSeconds) {
    statusTimer = setInterval(() => checkStatus(), Math.max(10, serverSeconds) * 1000);
  }
}

autoBox.checked = readPreference();
autoBox.addEventListener("change", () => {
  writePreference(autoBox.checked);
  checkStatus();
});
refreshButton.addEventListener("click", async () => {
  refreshButton.disabled = true;
  try {
    await checkStatus(true);
  } finally {
    refreshButton.disabled = false;
  }
});

(async () => {
  try {
    await showDataSize();
    await loadFacets();
  } catch (error) {
    statusLine.textContent = `API not reachable: ${error.message}`;
  }
  await render();
  await checkStatus();
})();
