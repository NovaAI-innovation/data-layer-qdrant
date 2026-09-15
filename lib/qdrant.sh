#!/usr/bin/env bash
# data-layer-qdrant/lib/qdrant.sh — bash-side helpers.
# Heavy lifting delegates to lib/qdrant.py.
set -euo pipefail
QDRANT_URL="${DATA_LAYER_QDRANT_URL:-http://localhost:6333}"
LIB="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
log() { printf '[qdrant.sh %s] %s\n' "$(date +%H:%M:%S)" "$*"; }

qdrant_url()      { echo "$QDRANT_URL"; }
qdrant_reachable(){ curl -fsS "$QDRANT_URL/healthz" >/dev/null 2>&1; }

qdrant_wait() {
  local max="${1:-30}"
  for _ in $(seq 1 "$max"); do
    qdrant_reachable && return 0
    sleep 1
  done
  return 1
}

qdrant_apply_collection() {
  /opt/venv/bin/python "$LIB/qdrant.py" apply-collection \
    --url "$QDRANT_URL" --name "$1" --schema "$2"
}

qdrant_apply_migrations() {
  local dir="${1:-$ROOT/../migrations}"
  : "${dir:=$LIB/../migrations}"
  qdrant_wait 30 || { log "qdrant not reachable"; return 1; }
  /opt/venv/bin/python "$LIB/qdrant.py" apply-migrations \
    --url "$QDRANT_URL" --dir "$dir"
}

qdrant_delete_collection() {
  /opt/venv/bin/python "$LIB/qdrant.py" delete-collection \
    --url "$QDRANT_URL" --name "$1"
}

delete-all-collections() {
  /opt/venv/bin/python "$LIB/qdrant.py" delete-all-collections --url "$QDRANT_URL"
}

# subcommand entry
if [ "${1:-}" = "delete-all-collections" ]; then
  shift
  delete-all-collections "$@"
fi
