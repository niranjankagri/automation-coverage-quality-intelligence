// The report's shell (docs/report-ui.md): hash routes (#/results?repository=...&kind=ui), the filter
// bar, the theme toggle and the sidebar. A section shows its skeleton at once; the newest navigation
// wins (older requests are cancelled), and Back returns to the same scroll position.

import { SCOPE_KEYS, api, href } from "./api.js";
import { h, present, repoName, skeleton } from "./dom.js";
import { coverage } from "./coverage.js";
import { failures } from "./failures.js";
import { filterBar } from "./filters.js";
import { overview } from "./overview.js";
import { requirement } from "./requirement.js";
import { results } from "./results.js";
import { testDetails } from "./test.js";
import { trends } from "./trends.js";

// section: [title, page, sidebar entry it belongs to]
const PAGES = {
  overview: ["Overview", overview, "overview"],
  results: ["Test Results", results, "results"],
  failures: ["Failures & Stability", failures, "failures"],
  trends: ["Trends", trends, "trends"],
  coverage: ["Coverage & Requirements", coverage, "coverage"],
  test: ["Test details", testDetails, "results"],
  requirement: ["Requirement", requirement, "coverage"],
};
// Earlier section names (first report version): old links and bookmarks keep working
const ALIASES = { suites: "results", categories: "failures", graphs: "trends", behaviors: "coverage" };
// Sections where a new scope keeps the page; anywhere else it opens the matching list
const SCOPE_TARGET = { test: "results", requirement: "coverage" };

const main = document.getElementById("main");
const filtersBox = document.getElementById("filters");
const themeButton = document.getElementById("theme");
const scrolls = new Map();
const facts = {};
let rendering = 0;
let controller = null;
let previous = "";

/** The current route: section, its own parameters and the scope. */
function route() {
  const [path, text = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(text);
  const scope = Object.fromEntries(SCOPE_KEYS.filter((key) => params.get(key)).map((key) => [key, params.get(key)]));
  return { section: path || "overview", params, scope, from: previous };
}

/** Navigate to the same section (or its list) with another scope; page parameters are dropped. */
function go(scope) {
  const { section } = route();
  location.hash = href(SCOPE_TARGET[section] ?? section, scope);
}

async function loadFacts(fresh = false) {
  const [options, status, health] = await Promise.allSettled([
    api("/api/report/options", { fresh }), api("/api/status", { fresh }), api("/api/health", { fresh })]);
  facts.options = options.value;
  facts.status = status.value;
  facts.health = health.value;
  if (facts.health) {
    document.getElementById("footer").replaceChildren(
      `Quality Intelligence ${facts.health.version} · ${facts.health.runs} runs · `,
      facts.health.catalog_notice ? `${facts.health.catalog_notice} · ` : "",
      h("a", { href: "/docs" }, "API documentation"));
  }
}

async function refresh() {
  await loadFacts(true);
  await render(true);
}

async function render(fresh = false) {
  const mine = ++rendering;
  const state = route();
  if (ALIASES[state.section]) return location.replace(`#/${ALIASES[state.section]}${location.hash.includes("?") ? `?${location.hash.split("?")[1]}` : ""}`);
  if (!PAGES[state.section]) return location.replace(href("overview", state.scope));
  const [title, page, nav] = PAGES[state.section];
  controller?.abort();
  controller = new AbortController();

  for (const link of document.querySelectorAll(".sidebar a[data-section]")) {
    link.href = href(link.dataset.section, state.scope);
    if (link.dataset.section === nav) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  filtersBox.replaceChildren(filterBar(state, facts, go, refresh));
  main.setAttribute("aria-busy", "true");
  main.replaceChildren(...skeleton(title));
  document.title = `${title} · ${repoName(state.scope.repository)} · Quality Intelligence report`;

  let content;
  try {
    content = await page(state, { facts, signal: controller.signal, fresh });
  } catch (error) {
    if (error.name === "AbortError") return;
    content = h("div", { class: "error-box", role: "alert" }, `Could not load ${title}. `, String(error.message), " ",
      h("button", { type: "button", class: "button-quiet", id: "retry" }, "Retry"));
  }
  if (mine !== rendering) return; // a newer navigation started meanwhile
  main.replaceChildren(...present(content));
  main.removeAttribute("aria-busy");
  document.getElementById("retry")?.addEventListener("click", () => render(true));
  window.scrollTo(0, scrolls.get(location.hash) ?? 0);
  // A link to one panel of a page (?panel=readiness, ?show=gaps) opens the page at that panel
  const panel = state.params.get("panel") ?? state.params.get("show");
  if (panel && !scrolls.has(location.hash)) document.getElementById(panel)?.scrollIntoView({ block: "start" });
  const heading = main.querySelector("h1");
  heading?.setAttribute("tabindex", "-1");
  if (!filtersBox.contains(document.activeElement)) heading?.focus({ preventScroll: true });
}

/** The portfolio's single theme button: light <-> dark, remembered as "na-theme". */
function setUpTheme() {
  const root = document.documentElement;
  const current = () =>
    root.dataset.theme === "light" || root.dataset.theme === "dark"
      ? root.dataset.theme
      : window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
  const label = () => {
    const dark = current() === "dark";
    themeButton.textContent = dark ? "☀" : "◐";
    themeButton.setAttribute("aria-label", dark ? "Use light theme" : "Use dark theme");
    themeButton.title = dark ? "Switch to light theme" : "Switch to dark theme";
  };
  themeButton.addEventListener("click", () => {
    root.dataset.theme = current() === "dark" ? "light" : "dark";
    try {
      localStorage.setItem("na-theme", root.dataset.theme);
    } catch (_) {
      /* Storage can be disabled. */
    }
    label();
  });
  label();
}

window.addEventListener("hashchange", (event) => {
  // Remember where the reader was, so Back (or "Back to results") returns to the same place
  const old = new URL(event.oldURL).hash;
  scrolls.set(old, window.scrollY);
  previous = old;
  render();
});
setUpTheme();
await loadFacts();
await render();
