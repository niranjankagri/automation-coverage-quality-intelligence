// Quality Intelligence dashboard: a small hash-routed single page over the JSON API.
// Every number shown comes from the API; this file only fetches, filters the URL and renders.
// All text is set with textContent (test names contain quotes, brackets and < >).
"use strict";

const FILTERS = ["repository", "feature", "criticality", "test_type", "framework", "environment", "browser", "build", "job", "since", "until"];
const RUN_FILTERS = ["repository", "framework", "environment", "browser", "build", "job", "since", "until"];
const FILTER_NAMES = { repository: "Repository", feature: "Feature", criticality: "Criticality", test_type: "Test type", framework: "Framework", environment: "Environment", browser: "Browser", build: "Build", job: "Job", since: "From", until: "To" };
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
  for (const [name, value] of Object.entries(extra)) if (value) params.set(name, value);
  const query = params.toString();
  return `#${path}${query ? `?${query}` : ""}`;
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

document.getElementById("filters").addEventListener("change", (event) => {
  const { parts, params } = route();
  if (event.target.value) params.set(event.target.name, event.target.value);
  else params.delete(event.target.name);
  const query = params.toString();
  location.hash = `#/${parts.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
});

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
  const active = FILTERS.filter((name) => params.get(name));
  list.replaceChildren(
    ...active.map((name) => {
      const remove = h("button", { type: "button", class: "chip-remove", "aria-label": `Remove filter ${FILTER_NAMES[name]}: ${params.get(name)}` }, "×");
      remove.addEventListener("click", () => setFilters({ [name]: "" }));
      return h("li", {}, h("span", { class: "chip" }, `${FILTER_NAMES[name]}: ${params.get(name)}`, remove));
    }),
  );
  list.hidden = active.length === 0;
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
  for (const name of FILTERS) params.delete(name);
  const query = params.toString();
  location.hash = `#/${parts.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
});

// ---- views -----------------------------------------------------------------------------

function metricCard(label, ratio, href, detail) {
  const percent = ratio.percent;
  return h(
    href ? "a" : "div",
    { class: "card", href },
    h("div", { class: "label" }, label),
    h("div", { class: "value" }, percent === null ? "n/a" : `${percent.toFixed(1)} %`),
    h("div", { class: "detail" }, `${ratio.numerator} of ${ratio.denominator}${detail ? ` · ${detail}` : ""}`),
    meter(percent ?? 0),
  );
}

/** Bar for a percentage. The width is set through the CSSOM: the CSP forbids style attributes. */
function meter(percent) {
  const bar = h("span");
  bar.style.width = `${percent}%`;
  return h("div", { class: "meter", "aria-hidden": "true" }, bar);
}

function countCard(label, value, href, detail) {
  return h(href ? "a" : "div", { class: "card", href }, h("div", { class: "label" }, label), h("div", { class: "value" }, value), detail ? h("div", { class: "detail" }, detail) : null);
}

/** Requirement ids as links; ``tone`` colours them (e.g. "critical", "failing"). */
function idChips(ids, tone) {
  if (!ids.length) return h("p", { class: "lead" }, "None.");
  return h("ul", { class: "chips" }, ids.map((id) => h("li", {}, h("a", { href: link(`/requirement/${encodeURIComponent(id)}`) }, h("span", { class: `badge ${tone}` }, id)))));
}

const STATE_TEXT = { ready: "Ready", "at risk": "At risk", blocked: "Blocked", unknown: "Unknown" };

function readinessPanel(r) {
  return h(
    "section",
    { class: `readiness ${r.state.replaceAll(" ", "-")}`, "aria-labelledby": "readiness-title" },
    h("h2", { id: "readiness-title" }, "Release status: ", badge(STATE_TEXT[r.state] ?? r.state)),
    h("p", { class: "sub" }, r.gate_name ? `Decided by the gate "${r.gate_name}" on the scope chosen above, plus the warnings it does not measure (docs/readiness.md).` : "No release gate is configured for this dashboard."),
    h("ul", { class: "reasons" }, r.reasons.map((reason) => h("li", {}, reason))),
    r.rules.length
      ? h(
          "details",
          {},
          h("summary", {}, `Gate rules (${r.rules.filter((x) => x.fails_gate).length} failing of ${r.rules.length})`),
          table(
            ["Rule", "Actual", "Expected", "Result"],
            r.rules.map((x) => h("tr", { class: x.fails_gate ? "failing-rule" : null }, h("td", {}, x.name, h("span", { class: "sub" }, x.explanation)), h("td", {}, x.actual), h("td", {}, x.expected), h("td", {}, x.fails_gate ? "fail" : x.status))),
            "",
          ),
        )
      : null,
    h(
      "div",
      { class: "cards" },
      // Coverage and pass rate have their own cards below; these are the figures only shown here
      countCard("Test executions", r.executions, link("/tests"), "latest run per context, in scope"),
      countCard("Critical without automation", r.critical_without_automation, link("/requirements", { criticality: "critical" })),
      countCard("Flaky candidates", r.flaky_candidates, link("/stability")),
      countCard("Incomplete pipelines (7 days)", r.incomplete_pipelines, link("/pipelines")),
      countCard("Latest collection", r.latest_collection_at ? formatDate(r.latest_collection_at) : "–", null, r.latest_collection_at ? "results collected from CI" : "no collection recorded"),
    ),
  );
}

async function overview() {
  const [s, r] = await Promise.all([api(`/api/summary${apiQuery(FILTERS)}`), api(`/api/readiness${apiQuery(FILTERS)}`)]);
  const c = s.outcome_counts;
  return [
    h("h1", {}, "Overview"),
    readinessPanel(r),
    h("p", { class: "lead" }, "Coverage comes from the requirement catalog; the pass rate comes from the latest run of each framework, environment and browser. They are separate numbers on purpose."),
    h("h2", {}, "Coverage"),
    h(
      "div",
      { class: "cards" },
      countCard("Requirements in scope", s.requirements_total, link("/requirements"), `${s.requirements_with_tests} with tests`),
      metricCard("Requirement coverage", s.requirement_coverage, link("/requirements", { status: "no tests" }), "with at least one test case"),
      metricCard("Automation coverage", s.automation_coverage, link("/requirements", { status: "not automated" }), "linked test cases automated"),
      metricCard("Automated requirement coverage", s.automated_requirement_coverage, link("/requirements", { status: "automated" }), "with an automated test"),
    ),
    h("h2", {}, "Execution (latest runs)"),
    h(
      "div",
      { class: "cards" },
      metricCard("Execution pass rate", s.pass_rate, link("/tests"), "skipped tests not counted"),
      countCard("Passed", c.passed, link("/tests", { outcome: "passed" })),
      countCard("Failed", c.failed, link("/tests", { outcome: "failed" })),
      countCard("Errors", c.error, link("/tests", { outcome: "error" })),
      countCard("Skipped", c.skipped, link("/tests", { outcome: "skipped" })),
    ),
    s.snapshot.length
      ? table(
          ["Run", "Framework", "Browser", "Build", "Started", { label: "Pass rate", num: true }],
          s.snapshot.map((r) =>
            h("tr", {}, h("td", {}, h("a", { href: link(`/run/${r.run_id}`) }, r.source)), h("td", {}, r.context.framework ?? "–"), h("td", {}, r.context.browser ?? "–"), h("td", {}, r.context.build ?? "–"), h("td", { class: "nowrap" }, formatDate(r.started_at)), h("td", { class: "num" }, r.pass_rate.text)),
          ),
          "",
        )
      : h("p", { class: "empty" }, "No runs in this scope (or no result files were loaded), so there is no execution status."),
    h("h2", {}, `Critical requirements without automation (${s.uncovered_critical.length})`),
    idChips(s.uncovered_critical.map((r) => r.id), "critical"),
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

function matrixTable(title, rows) {
  const coverage = ["no tests", "not automated", "automated"];
  const execution = ["failing", "not run", "skipped", "passing"];
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
          coverage.map((c) => h("td", { class: "num" }, r.coverage[c] ? h("a", { href: link("/requirements", { status: c, [title === "By criticality" ? "criticality" : "feature"]: r.group }) }, String(r.coverage[c])) : "0")),
          execution.map((e) => h("td", { class: "num" }, String(r.execution[e] ?? 0))),
          h("td", { class: "num" }, String(r.stale)),
        ),
      ),
      "No requirements in scope.",
      { tools: false },
    ),
  ];
}

async function requirementsView() {
  const status = route().params.get("status") ?? "";
  const [rows, matrix] = await Promise.all([api(`/api/requirements${apiQuery(FILTERS, { status })}`), api(`/api/requirements/matrix${apiQuery(FILTERS)}`)]);
  const statusSelect = h("select", { id: "status-filter" }, ["", "no tests", "not automated", "automated", "passing", "failing", "not run", "skipped"].map((v) => h("option", { value: v }, v || "Any")));
  statusSelect.value = status;
  statusSelect.addEventListener("change", () => (location.hash = link("/requirements", { status: statusSelect.value })));
  return [
    h("h1", {}, "Requirements"),
    h("p", { class: "lead" }, `${rows.length} requirement(s) in scope.`),
    h(
      "details",
      { class: "matrix", open: status ? null : "" },
      h("summary", {}, "Coverage by criticality and feature"),
      h("p", { class: "sub" }, `Counts come from the API for the scope above. Evidence is stale when the latest execution of a requirement's tests is older than ${matrix.stale_days} days. Click a coverage count to list those requirements.`),
      matrixTable("By criticality", matrix.by_criticality),
      matrixTable("By feature", matrix.by_feature),
    ),
    h(
      "div",
      { class: "toolbar" },
      h("label", { for: "status-filter" }, "Status", statusSelect),
      h("a", { href: link("/requirements", { status: "no tests", criticality: "critical" }) }, "Uncovered critical requirements"),
    ),
    h("h2", { id: "requirement-list", class: "visually-hidden" }, "Requirement list"),
    h("section", { "aria-labelledby": "requirement-list" }, table(
      ["Requirement", "Feature", "Criticality", { label: "Automated / cases", num: true }, "Coverage", "Execution", "Latest evidence"],
      rows.map((r) =>
        h(
          "tr",
          {},
          h("td", {}, h("a", { href: link(`/requirement/${encodeURIComponent(r.id)}`) }, r.id), h("span", { class: "sub" }, r.title)),
          h("td", {}, r.feature),
          h("td", {}, r.criticality === "critical" ? badge("critical") : r.criticality),
          h("td", { class: "num" }, `${r.automated_test_cases} / ${r.test_cases}`),
          h("td", {}, badge(r.coverage_status)),
          h("td", {}, badge(r.execution_status)),
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
      withTest ? h("td", {}, h("a", { class: "key", href: link("/test", { key: e.key }) }, e.key)) : null,
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

async function requirementDetail(id) {
  const d = await api(`/api/requirements/${encodeURIComponent(id)}${apiQuery(RUN_FILTERS)}`);
  const r = d.requirement;
  return [
    h("p", {}, h("a", { href: link("/requirements") }, "← Requirements")),
    h("h1", {}, `${r.id}: ${r.title}`),
    r.description ? h("p", { class: "lead" }, r.description) : null,
    h("dl", { class: "meta" }, h("dt", {}, "Feature"), h("dd", {}, r.feature), h("dt", {}, "Criticality"), h("dd", {}, r.criticality), h("dt", {}, "Priority / risk"), h("dd", {}, `${r.priority} / ${r.risk}`), h("dt", {}, "Platforms"), h("dd", {}, r.platforms.join(", ") || "unspecified"), h("dt", {}, "Coverage"), h("dd", {}, badge(r.coverage_status)), h("dt", {}, "Execution"), h("dd", {}, badge(r.execution_status))),
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
      h("td", {}, h("a", { class: "key", href: link("/test", { key: r.key }) }, r.key), r.last_failure ? h("span", { class: "sub" }, `last failure: ${r.last_failure}`) : null),
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
    table(["Test", "Framework", { label: "Runs", num: true }, { label: "Passed", num: true }, { label: "Failed", num: true }, { label: "Errors", num: true }, { label: "Skipped", num: true }, "Latest", "Test case"], body, "No tests in the loaded runs match these filters.", { tools: true, searchLabel: "Search", searchId: "test-search", searchPlaceholder: "part of the name", name: "tests" }),
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
  return [
    h("p", {}, h("a", { href: link("/tests") }, "← Tests")),
    h("h1", { class: "key" }, d.key),
    h("div", { class: "toolbar" }, copyButton("Copy test identifier", d.key), copyButton("Copy investigation link", shareLink)),
    h(
      "dl",
      { class: "meta" },
      h("dt", {}, "Latest result"),
      h("dd", {}, badge(latest.outcome), " ", formatDate(latest.started_at), latest.retries ? ` after ${latest.retries} retr${latest.retries === 1 ? "y" : "ies"}` : ""),
      h("dt", {}, "Context"),
      h("dd", {}, [latest.context.framework, latest.context.environment, latest.context.browser, latest.context.platform].map((v) => v ?? "–").join(" / "), ` · build ${latest.context.build ?? "–"}`),
      h("dt", {}, "Source"),
      h("dd", {}, h("a", { href: link(`/run/${latest.run_id}`) }, latest.source), latest.pipeline ? ` · pipeline ${pipelineLabel(latest.pipeline)}` : "", latest.ci_url ? [" · ", external(latest.ci_url, "CI run on GitHub")] : null),
      h("dt", {}, "Requirements"),
      h("dd", {}, d.requirements.length ? d.requirements.map((rid, i) => [i ? ", " : "", h("a", { href: link(`/requirement/${encodeURIComponent(rid)}`) }, rid)]) : "none linked"),
      h("dt", {}, "Test cases"),
      h("dd", {}, d.test_cases.join(", ") || "none (unmatched)"),
      h("dt", {}, "Pattern"),
      h("dd", {}, h("ol", { class: "pattern", "aria-label": `${d.passed} passed, ${d.failed} failed or errored, oldest first` }, oldestFirst.map((e) => h("li", { class: `dot ${e.outcome}`, title: `${formatDate(e.started_at)}: ${e.outcome}` }, e.outcome[0].toUpperCase()))), h("span", { class: "sub" }, `${d.passed} passed, ${d.failed} failed or errored of ${d.executions.length}, oldest first`)),
    ),
    latest.failure ? [h("h2", {}, "Latest failure"), failureDetails(latest.failure)] : null,
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

async function compareView() {
  const params = route().params;
  const builds = await api(`/api/builds${apiQuery(RUN_FILTERS)}`);
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
  ];
  if (builds.length < 2) return [...header, h("p", { class: "empty" }, "At least two builds are needed in this scope.")];
  if (base === head) return [...header, h("p", { class: "empty" }, "Choose two different builds.")];
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
    );
  const category = params.get("change") ?? "";
  const shown = d.changes.filter((c) => !category || c.category === category);
  return [
    ...header,
    h("div", { class: "cards" }, side("Baseline", d.base), side("Comparison", d.head)),
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
          h("td", {}, h("a", { class: "key", href: link("/test", { key: c.key }) }, c.key)),
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
      rows.map((r) => h("tr", {}, h("td", {}, h("a", { href: link(`/run/${r.run_id}`) }, r.source)), h("td", {}, pipelineLabel(r.pipeline)), h("td", {}, r.context.framework ?? "–"), h("td", {}, r.context.browser ?? "–"), h("td", {}, r.context.build ?? "–"), h("td", { class: "nowrap" }, formatDate(r.started_at)), OUTCOMES.map((o) => h("td", { class: "num" }, r.counts[o])), h("td", { class: "num" }, r.pass_rate.text))),
      "No runs match these filters.",
    ),
  ];
}

async function runDetail(runId) {
  const d = await api(`/api/runs/${encodeURIComponent(runId)}`);
  const r = d.run;
  return [
    h("p", {}, h("a", { href: link("/runs") }, "← Runs")),
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
            h("td", {}, j.run_ids.length === 1 ? h("a", { href: link(`/run/${j.run_ids[0]}`) }, j.name) : j.name, j.expected ? null : h("span", { class: "sub" }, "not an expected job")),
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
  const d = await api(`/api/pipelines${apiQuery(RUN_FILTERS, { jobs, status, workflow })}`);
  const jobsInput = h("input", { id: "expected-jobs", type: "text", value: jobs, placeholder: "api, ui-chrome, ui-firefox", size: "40" });
  jobsInput.addEventListener("change", () => (location.hash = link("/pipelines", { jobs: jobsInput.value.trim(), status, workflow })));
  const workflowSelect = h("select", { id: "workflow" }, h("option", { value: "" }, "All"), d.workflows.map((w) => h("option", { value: w }, w)));
  workflowSelect.value = workflow;
  workflowSelect.addEventListener("change", () => (location.hash = link("/pipelines", { jobs, status, workflow: workflowSelect.value })));
  const statuses = [...STATUS_ORDER.filter((s) => s in d.status_counts), ...Object.keys(d.status_counts).filter((s) => !STATUS_ORDER.includes(s))];
  const total = Object.values(d.status_counts).reduce((a, b) => a + b, 0);
  return [
    h("h1", {}, "Pipelines"),
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
      : d.pipelines.map((p, i) => pipelineDetails(p, i === 0)),
  ];
}

async function collectionView() {
  const d = await api("/api/collection");
  return [
    h("h1", {}, "Collection"),
    h("p", { class: "lead" }, `Results collected from CI per repository (docs/collection.md). A repository is overdue when its last collection is older than ${d.expected_hours} hours.`),
    d.workflow_url ? h("p", {}, external(d.workflow_url, "Open the collection workflow on GitHub")) : null,
    d.notes.length ? h("div", { class: "notice", role: "note" }, d.notes.map((n) => h("p", {}, n))) : null,
    table(
      ["Repository", "Workflows", "Last collection", "Freshness", { label: "Pipelines (7 d)", num: true }, { label: "Complete", num: true }, { label: "Incomplete", num: true }, { label: "Results", num: true }, "CI conclusions"],
      d.repositories.map((r) =>
        h(
          "tr",
          { class: r.fresh ? null : "missing" },
          h("td", {}, h("a", { href: link("/pipelines", { repository: r.repository }) }, r.repository)),
          h("td", {}, r.workflows.join(", ")),
          h("td", { class: "nowrap" }, formatDate(r.last_collected_at)),
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
    d.repositories.some((r) => r.problems.length)
      ? [h("h2", {}, "Missing artifacts and ingestion problems (7 days)"), h("ul", { class: "reasons" }, d.repositories.flatMap((r) => r.problems.map((p) => h("li", {}, `${r.repository}: ${p}`))))]
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
          h("td", {}, h("a", { class: "key", href: link("/test", { key: r.key }) }, r.key), r.last_failure ? h("span", { class: "sub" }, `last failure: ${r.last_failure.split("\n")[0].slice(0, 160)}`) : null),
          h("td", {}, r.context),
          h("td", {}, badge(r.status), r.status === "flaky candidate" ? h("span", { class: "sub" }, "suspected") : null),
          h("td", { class: "num" }, r.failure_rate.text),
          h("td", { class: "nowrap" }, formatDate(r.last_failed_at)),
          h("td", { class: "num" }, String(r.affected_builds.length), r.affected_builds.length ? h("span", { class: "sub" }, r.affected_builds.join(", ")) : null),
          h("td", {}, h("ul", { class: "reasons" }, r.reasons.map((reason) => h("li", {}, reason)))),
          h("td", {}, r.last_failing_run_id ? h("a", { href: link(`/run/${r.last_failing_run_id}`) }, "last failing") : "–", r.last_passing_run_id ? [" · ", h("a", { href: link(`/run/${r.last_passing_run_id}`) }, "last passing")] : null),
          h("td", {}, r.test_cases.join(", ") || "–"),
        ),
      ),
      "No test needs attention in this window: every test is stable or has too little history.",
    ),
    h("h2", {}, `Recurring failures (${d.recurring_failures.length})`),
    table(
      ["Failure signature", { label: "Runs", num: true }, { label: "Times", num: true }, "Tests"],
      d.recurring_failures.map((f) => h("tr", {}, h("td", { class: "key" }, f.signature), h("td", { class: "num" }, f.runs), h("td", { class: "num" }, f.occurrences), h("td", {}, f.tests.map((t) => h("span", { class: "sub key" }, t))))),
      "No failure cause appeared in more than one run.",
    ),
    h("h2", {}, `Duration regressions (${d.duration_regressions.length})`),
    table(
      ["Test", "Context", { label: "Baseline", num: true }, { label: "Latest", num: true }],
      d.duration_regressions.map((r) => h("tr", {}, h("td", {}, h("a", { class: "key", href: link("/test", { key: r.key }) }, r.key)), h("td", {}, r.context), h("td", { class: "num" }, `${formatSeconds(r.baseline_seconds)} (${r.baseline_runs} runs)`), h("td", { class: "num" }, formatSeconds(r.latest_seconds)))),
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
                points.map((p) => h("li", {}, h("a", { href: link(`/run/${p.run_id}`), class: p.failed ? "bad" : "good", title: `${formatDate(p.started_at)} · build ${p.build ?? "–"} · ${p.pass_rate.text}` }, h("span", { class: "sr" }, `${formatDate(p.started_at)}: ${p.pass_rate.text}`)))),
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
function stackedBars(labels, series, unit = "", hrefs = null) {
  const totals = labels.map((_, i) => series.reduce((sum, item) => sum + (item.values[i] ?? 0), 0));
  const max = Math.max(1, ...totals);
  const f = frame(labels, max, unit);
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

async function trendsView() {
  const d = await api(`/api/trends${apiQuery(FILTERS)}`);
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

const VIEWS = {
  "": overview,
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
};

// Each render gets a number; only the latest may write to the page. Without this, a slow
// response for an older address (e.g. the first of two quickly changed filters) arrives last
// and shows data that no longer matches the address (seen in CI).
let renderCount = 0;

async function render() {
  const current = ++renderCount;
  const { parts } = route();
  const name = parts[0] ?? "";
  const section = { requirement: "requirements", test: "tests", run: "runs", "": "overview" }[name] ?? name;
  for (const a of document.querySelectorAll("nav a")) {
    // Section links keep the active filters, like every other link on the page
    a.setAttribute("href", link(a.dataset.nav === "overview" ? "/" : `/${a.dataset.nav}`));
    if (a.dataset.nav === section) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  }
  syncFilterForm();
  showActiveFilters();
  const handler = VIEWS[name];
  statusLine.textContent = "Loading…";
  try {
    if (!handler) throw new Error("This page does not exist.");
    const content = await handler(parts);
    if (current !== renderCount) return; // a newer address is being rendered
    // Views may leave empty slots (cond ? node : null); they must not show up as "null"
    view.replaceChildren(...[content].flat(3).filter((node) => node != null));
    statusLine.textContent = "";
    document.title = `${document.querySelector("#view h1")?.textContent ?? "Overview"} · Quality Intelligence`;
  } catch (error) {
    if (current !== renderCount) return;
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
  document.getElementById("data-size").textContent = `${health.requirements} requirements · ${health.runs} runs · qi ${health.version}`;
}

function describe(status) {
  const parts = [`Data loaded ${formatDate(status.loaded_at)}`];
  if (status.latest_run_started_at) parts.push(`latest run ${formatDate(status.latest_run_started_at)}`);
  if (status.latest_collection_at) parts.push(`last collection ${formatDate(status.latest_collection_at)}`);
  if (status.incomplete_collections_7d) parts.push(`${status.incomplete_collections_7d} incomplete collection(s) in 7 days`);
  if (!status.refresh_seconds) parts.push("this server does not reload");
  return parts.join(" · ");
}

let checking = false;

async function checkStatus(force = false) {
  if (checking) return; // one check at a time; a slow answer is not overtaken by another
  checking = true;
  const previous = freshLine.textContent;
  if (force) freshLine.textContent = "Checking for new data…"; // the content below stays
  try {
    await runCheck(force);
  } catch (error) {
    freshLine.textContent = previous;
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
  freshLine.textContent = describe(status);
  staleNote.hidden = !status.stale;
  if (status.stale) {
    staleNote.textContent = `The last refresh failed (${formatDate(status.last_error_at)}): ${status.last_error}. The figures shown are from ${formatDate(status.loaded_at)}.`;
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
