// The report's shell: hash routes (#/overview?repository=...), the repository switcher, the theme
// toggle and the sidebar (docs/report-ui.md). Pages render into <main>; the newest navigation wins.

import { api, scopeQuery } from "./api.js";
import { h, repoName } from "./dom.js";
import { overview } from "./overview.js";
import { suites } from "./suites.js";

// Sections still to come: each says so and links the classic page that has the data today
const COMING = {
  categories: { title: "Categories", what: "failures grouped by cause, with their tests, runs and an issue draft", classic: "/#/stability" },
  graphs: { title: "Graphs", what: "results per day, durations, regressions and the release gate over time", classic: "/#/trends" },
  behaviors: { title: "Behaviors", what: "requirements, their test cases and the coverage gaps by owner", classic: "/#/coverage" },
};
const PAGES = { overview, suites };
const TITLES = { overview: "Overview", suites: "Suites" };

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
  if (!PAGES[state.section] && !COMING[state.section]) return go("overview", state.repository);
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
    content = PAGES[state.section] ? await PAGES[state.section](state) : coming(state);
  } catch (error) {
    content = h("div", { class: "error-box", role: "alert" }, "Could not load this page. ", String(error.message), " ",
      h("button", { type: "button", class: "pill-link", id: "retry" }, "Retry"));
  }
  if (mine !== rendering) return; // a newer navigation started meanwhile
  main.replaceChildren(...[content].flat(Infinity).filter((part) => part !== null && part !== undefined));
  main.removeAttribute("aria-busy");
  document.getElementById("retry")?.addEventListener("click", render);
  const title = COMING[state.section]?.title ?? TITLES[state.section];
  document.title = `${title} · ${repoName(state.repository)} · Quality Intelligence report`;
  main.querySelector("h1")?.setAttribute("tabindex", "-1");
  if (document.activeElement !== select) main.querySelector("h1")?.focus({ preventScroll: true });
}

/** A section of the plan that is not built yet: what it will show, and where the data is today. */
function coming(state) {
  const page = COMING[state.section];
  return [
    h("p", { class: "eyebrow" }, `Report · ${repoName(state.repository)}`),
    h("h1", {}, page.title),
    h("div", { class: "card next-step" },
      h("p", {}, `This section will show ${page.what}. It is being built next.`),
      h("p", {}, h("a", { class: "button", href: `${page.classic}${scopeQuery(state.repository)}` }, "Open it in the classic dashboard"))),
  ];
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
