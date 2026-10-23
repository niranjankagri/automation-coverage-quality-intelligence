// The report's shell: hash routes (#/overview?repository=...), the repository switcher, the theme
// toggle and the sidebar (docs/report-ui.md). Pages render into <main>; the newest navigation wins.

import { api, scopeQuery } from "./api.js";
import { h, repoName } from "./dom.js";
import { overview } from "./overview.js";
import { behaviors } from "./behaviors.js";
import { categories } from "./categories.js";
import { graphs } from "./graphs.js";
import { suites } from "./suites.js";

const PAGES = { overview, categories, suites, graphs, behaviors };
const TITLES = { overview: "Overview", categories: "Categories", suites: "Suites", graphs: "Graphs", behaviors: "Behaviors" };

const main = document.getElementById("main");
const select = document.getElementById("repository");
const themeButton = document.getElementById("theme");
let rendering = 0;

/** The current route: section name and the repository in scope ("" = all). */
function route() {
  const [path, query = ""] = location.hash.replace(/^#\/?/, "").split("?");
  const params = new URLSearchParams(query);
  return { section: path || "overview", repository: params.get("repository") ?? "", params };
}

/** The same section with another repository (or all of them). */
function go(section, repository) {
  location.hash = `#/${section}${scopeQuery(repository)}`;
}

async function render() {
  const mine = ++rendering;
  const state = route();
  if (!PAGES[state.section]) return go("overview", state.repository);
  select.value = state.repository;
  if (select.value !== state.repository) select.append(h("option", { value: state.repository }, repoName(state.repository)));
  select.value = state.repository;
  for (const link of document.querySelectorAll(".sidebar a[data-section]")) {
    link.href = `#/${link.dataset.section}${scopeQuery(state.repository)}`;
    if (link.dataset.section === state.section) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  }
  main.setAttribute("aria-busy", "true");
  let content;
  try {
    content = await PAGES[state.section](state);
  } catch (error) {
    content = h("div", { class: "error-box", role: "alert" }, "Could not load this page. ", String(error.message), " ",
      h("button", { type: "button", class: "pill-link", id: "retry" }, "Retry"));
  }
  if (mine !== rendering) return; // a newer navigation started meanwhile
  main.replaceChildren(...[content].flat(Infinity).filter((part) => part !== null && part !== undefined));
  main.removeAttribute("aria-busy");
  document.getElementById("retry")?.addEventListener("click", render);
  document.title = `${TITLES[state.section]} · ${repoName(state.repository)} · Quality Intelligence report`;
  main.querySelector("h1")?.setAttribute("tabindex", "-1");
  if (document.activeElement !== select) main.querySelector("h1")?.focus({ preventScroll: true });
}

async function loadRepositories() {
  try {
    const facets = await api("/api/facets");
    const current = select.value;
    // Spread: replaceChildren takes nodes, an array of options would become text
    select.replaceChildren(h("option", { value: "" }, "All repositories"),
      ...facets.repositories.map((repository) => h("option", { value: repository }, repoName(repository))));
    select.value = current;
    if (!facets.repositories.length) select.title = "No collected repositories: results come from imported files";
  } catch (_) {
    /* The switcher keeps "All repositories"; the page shows its own error. */
  }
}

async function loadFooter() {
  try {
    const health = await api("/api/health");
    document.getElementById("footer").replaceChildren(
      `Quality Intelligence ${health.version} · ${health.runs} runs · `,
      health.catalog_notice ? `${health.catalog_notice} · ` : "",
      h("a", { href: "/docs" }, "API documentation"));
  } catch (_) {
    /* No footer details without the API. */
  }
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

select.addEventListener("change", () => go(route().section, select.value));
window.addEventListener("hashchange", render);
// Back/forward between selections pushed with history.pushState (Suites)
window.addEventListener("popstate", render);
setUpTheme();
loadFooter();
await loadRepositories();
await render();
