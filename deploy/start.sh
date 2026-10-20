#!/bin/sh
# Start of the hosted dashboard (docs/deployment.md). The platform's disk does not survive a
# restart, so the history published by the collection workflow is fetched first (no valid
# history: no start, the platform retries), then again every QI_FETCH_SECONDS; the dashboard
# reloads when the verified file has been swapped in, and keeps its data when a fetch fails.
set -eu

DATABASE=/data/quality.db
: "${QI_HISTORY_URL:?QI_HISTORY_URL must name the published history}"

qi history fetch "$QI_HISTORY_URL" --database "$DATABASE"

(
  while sleep "${QI_FETCH_SECONDS:-3600}"; do
    qi history fetch "$QI_HISTORY_URL" --database "$DATABASE" \
      || echo "qi: history fetch failed; the dashboard keeps its current data" >&2
  done
) &

exec qi dashboard \
  --catalog /app/samples/catalog.toml \
  --gate /app/samples/gates/nightly.toml \
  --database "$DATABASE" \
  --host 0.0.0.0 --port "${PORT:-8000}"
