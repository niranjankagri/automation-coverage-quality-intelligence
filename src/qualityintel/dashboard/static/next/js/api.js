// The report reads the same read-only JSON API as the classic dashboard (docs/dashboard.md).

/** GET ``path`` as JSON; a failed request throws with the server's message. */
export async function api(path) {
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

/** ``?repository=...`` for the chosen repository, nothing for "All repositories". */
export function scopeQuery(repository, extra = {}) {
  const params = new URLSearchParams();
  if (repository) params.set("repository", repository);
  for (const [name, value] of Object.entries(extra)) if (value) params.set(name, value);
  const query = params.toString();
  return query ? `?${query}` : "";
}
