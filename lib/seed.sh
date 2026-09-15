#!/usr/bin/env bash
# data-layer-qdrant/lib/seed.sh — bash wrapper around lib/seed.py.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
URL="${DATA_LAYER_QDRANT_URL:-http://localhost:6333}"
CSV=""
COLL="mpg_source_authority_documents"
log() { printf '[qdrant.seed %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '[qdrant.seed FAIL] %s\n' "$*" >&2; exit 3; }

while [ "${1:-}" != "" ]; do
  case "$1" in
    --url)        URL="$2"; shift 2 ;;
    --csv)        CSV="$2"; shift 2 ;;
    --collection) COLL="$2"; shift 2 ;;
    *)            fail "unknown arg: $1" ;;
  esac
done

if [ -z "$CSV" ]; then
  CSV="${DATA_LAYER_SOT_FIXTURE_CSV:-/a0/usr/workdir/MPG_DBSS_E2E_V03/MPG_DBSS_SOURCE_AUTHORITY_CONTROLLED_FIXTURE_v03.csv}"
fi
[ -f "$CSV" ] || fail "CSV not found: $CSV"

log "seeding $URL collection=$COLL from $CSV"
/opt/venv/bin/python "$ROOT/lib/seed.py" \
    --url "$URL" --csv "$CSV" --collection "$COLL"
log "seed complete"
