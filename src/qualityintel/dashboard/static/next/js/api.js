// The report reads the same read-only JSON API as the classic dashboard (docs/dashboard.md). The
// scope (repository, test type, browser, environment, dates) travels in every address and request.

/** Scope parameters, in the order of the filter bar; ``job`` is set by drill-downs into one job. */
export const SCOPE_KEYS = ["repository", "kind", "browser", "environment", "job", "since", "until"];

/** GET ``path`` as JSON; a failed request throws with the server's message. */
export async function api(path, { signal, fresh = false } = {}) {
  const response = await fetch(path, { headers: { Accept: "application/json" }, signal, cache: fresh ? "no-store" : "default" });
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

/** ``?repository=...&kind=...`` for the scope plus ``extra``; empty values are left out. */
export function query(scope = {}, extra = {}) {
  const params = new URLSearchParams();
  for (const key of SCOPE_KEYS) if (scope[key]) params.set(key, scope[key]);
  for (const [name, value] of Object.entries(extra)) if (value !== undefined && value !== null && value !== "") params.set(name, value);
  const text = params.toString();
  return text ? `?${text}` : "";
}

/** The address of a report section in this scope, e.g. ``href("results", scope, { status: "failed" })``. */
export const href = (section, scope, extra = {}) => `#/${section}${query(scope, extra)}`;

/** The scope without the keys given, for links that widen it (``without(scope, "browser")``). */
export const without = (scope, ...keys) => Object.fromEntries(Object.entries(scope).filter(([key]) => !keys.includes(key)));
