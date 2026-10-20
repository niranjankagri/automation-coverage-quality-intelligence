// Quality Intelligence dashboard: a small hash-routed single page over the JSON API.
// Every number shown comes from the API; this file only fetches, filters the URL and renders.
// All text is set with textContent (test names contain quotes, brackets and < >).
"use strict";

const FILTERS = ["feature", "criticality", "test_type", "framework", "environment", "browser"];
const RUN_FILTERS = ["framework", "environment", "browser"];
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

function table(headers, rows, emptyText) {
  if (!rows.length) return h("div", { class: "table-wrap" }, h("p", { class: "empty" }, emptyText));
  return h(
    "div",
    { class: "table-wrap" },
    h(
      "table",
      {},
      h("thead", {}, h("tr", {}, headers.map((x) => h("th", { scope: "col", class: x.num ? "num" : null }, x.label ?? x)))),
      h("tbody", {}, rows),
    ),
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
  for (const select of document.querySelectorAll("#filters select")) select.value = params.get(select.name) ?? "";
}

document.getElementById("filters").addEventListener("change", (event) => {
  const { parts, params } = route();
  if (event.target.value) params.set(event.target.name, event.target.value);
  else params.delete(event.target.name);
  const query = params.toString();
  location.hash = `#/${parts.map(encodeURIComponent).join("/")}${query ? `?${query}` : ""}`;
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

async function overview() {
  const s = await api(`/api/summary${apiQuery(FILTERS)}`);
  const c = s.outcome_counts;
  return [
    h("h1", {}, "Overview"),
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

async function requirementsView() {
  const status = route().params.get("status") ?? "";
  const rows = await api(`/api/requirements${apiQuery(FILTERS, { status })}`);
  const statusSelect = h("select", { id: "status-filter" }, ["", "no tests", "not automated", "automated", "passing", "failing", "not run", "skipped"].map((v) => h("option", { value: v }, v || "Any")));
  statusSelect.value = status;
  statusSelect.addEventListener("change", () => (location.hash = link("/requirements", { status: statusSelect.value })));
  return [
    h("h1", {}, "Requirements"),
    h("p", { class: "lead" }, `${rows.length} requirement(s) in scope.`),
    h("div", { class: "toolbar" }, h("label", { for: "status-filter" }, "Status", statusSelect)),
    table(
      ["Requirement", "Feature", "Criticality", { label: "Automated / cases", num: true }, "Coverage", "Execution"],
      rows.map((r) =>
        h("tr", {}, h("td", {}, h("a", { href: link(`/requirement/${encodeURIComponent(r.id)}`) }, r.id), h("span", { class: "sub" }, r.title)), h("td", {}, r.feature), h("td", {}, r.criticality === "critical" ? badge("critical") : r.criticality), h("td", { class: "num" }, `${r.automated_test_cases} / ${r.test_cases}`), h("td", {}, badge(r.coverage_status)), h("td", {}, badge(r.execution_status))),
      ),
      "No requirements match these filters.",
    ),
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
  const search = h("input", { type: "search", id: "test-search", placeholder: "part of the name" });
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
  search.addEventListener("input", () => {
    const needle = search.value.trim().toLowerCase();
    for (const tr of body) tr.hidden = needle !== "" && !tr.dataset.key.includes(needle);
  });
  return [
    h("h1", {}, "Tests"),
    h("p", { class: "lead" }, `${rows.length} test(s) across all loaded runs; tests with failures first.`),
    h("div", { class: "toolbar" }, h("label", { for: "test-search" }, "Search", search), h("label", { for: "outcome-filter" }, "Latest outcome", outcomeSelect)),
    table(["Test", "Framework", { label: "Runs", num: true }, { label: "Passed", num: true }, { label: "Failed", num: true }, { label: "Errors", num: true }, { label: "Skipped", num: true }, "Latest", "Test case"], body, "No tests in the loaded runs match these filters."),
  ];
}

async function testHistory() {
  const key = route().params.get("key") ?? "";
  const d = await api(`/api/tests/history${apiQuery(RUN_FILTERS, { key })}`);
  return [
    h("p", {}, h("a", { href: link("/tests") }, "← Tests")),
    h("h1", { class: "key" }, d.key),
    h("p", { class: "lead" }, `Test case: ${d.test_cases.join(", ") || "none (unmatched)"} · ${d.executions.length} execution(s), newest first.`),
    table(EXECUTION_HEADERS.slice(1), executionRows(d.executions, false), "No executions."),
  ];
}

async function runsView() {
  const rows = await api(`/api/runs${apiQuery(RUN_FILTERS)}`);
  return [
    h("h1", {}, "Runs"),
    h("p", { class: "lead" }, `${rows.length} imported run(s), newest first.`),
    table(
      ["Run", "Framework", "Browser", "Build", "Started", ...OUTCOMES.map((o) => ({ label: o, num: true })), { label: "Pass rate", num: true }],
      rows.map((r) => h("tr", {}, h("td", {}, h("a", { href: link(`/run/${r.run_id}`) }, r.source)), h("td", {}, r.context.framework ?? "–"), h("td", {}, r.context.browser ?? "–"), h("td", {}, r.context.build ?? "–"), h("td", { class: "nowrap" }, formatDate(r.started_at)), OUTCOMES.map((o) => h("td", { class: "num" }, r.counts[o])), h("td", { class: "num" }, r.pass_rate.text))),
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
    h("dl", { class: "meta" }, h("dt", {}, "Framework"), h("dd", {}, r.context.framework ?? "–"), h("dt", {}, "Environment"), h("dd", {}, r.context.environment ?? "–"), h("dt", {}, "Browser / platform"), h("dd", {}, `${r.context.browser ?? "–"} / ${r.context.platform ?? "–"}`), h("dt", {}, "Build"), h("dd", {}, r.context.build ?? "–"), h("dt", {}, "Started"), h("dd", {}, formatDate(r.started_at)), h("dt", {}, "Pass rate"), h("dd", {}, r.pass_rate.text)),
    table(EXECUTION_HEADERS, executionRows(d.executions), "This run has no results."),
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
    table(
      ["Test", "Context", "Status", { label: "Failure rate", num: true }, "Evidence", "Test case"],
      d.rows.map((r) =>
        h(
          "tr",
          {},
          h("td", {}, h("a", { class: "key", href: link("/test", { key: r.key }) }, r.key), r.last_failure ? h("span", { class: "sub" }, `last failure: ${r.last_failure.split("\n")[0].slice(0, 160)}`) : null),
          h("td", {}, r.context),
          h("td", {}, badge(r.status)),
          h("td", { class: "num" }, r.failure_rate.text),
          h("td", {}, h("ul", { class: "reasons" }, r.reasons.map((reason) => h("li", {}, reason)))),
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

// ---- main loop -------------------------------------------------------------------------

const VIEWS = {
  "": overview,
  requirements: requirementsView,
  requirement: (parts) => requirementDetail(parts[1]),
  tests: testsView,
  test: testHistory,
  runs: runsView,
  run: (parts) => runDetail(parts[1]),
  stability: stabilityView,
};

async function render() {
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
  const handler = VIEWS[name];
  statusLine.textContent = "Loading…";
  try {
    if (!handler) throw new Error("This page does not exist.");
    const content = await handler(parts);
    view.replaceChildren(...[content].flat(3));
    statusLine.textContent = "";
    document.title = `${document.querySelector("#view h1")?.textContent ?? "Overview"} · Quality Intelligence`;
  } catch (error) {
    view.replaceChildren(h("div", { class: "error", role: "alert" }, h("strong", {}, "Could not load this view. "), error.message, " ", h("button", { type: "button", id: "retry" }, "Retry")));
    document.getElementById("retry").addEventListener("click", render);
    statusLine.textContent = "";
  }
}

window.addEventListener("hashchange", render);
(async () => {
  try {
    const health = await api("/api/health");
    document.getElementById("data-size").textContent = `${health.requirements} requirements · ${health.runs} runs · qi ${health.version}`;
    await loadFacets();
  } catch (error) {
    statusLine.textContent = `API not reachable: ${error.message}`;
  }
  await render();
})();
