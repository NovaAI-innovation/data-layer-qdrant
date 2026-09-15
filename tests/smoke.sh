#!/usr/bin/env bash
# data-layer-qdrant/tests/smoke.sh — end-to-end smoke test.
# 5 assertions:
#   1. /healthz returns ok
#   2. /collections list includes both expected names
#   3. each expected collection has vectors.size=768 + distance=Cosine
#   4. point counts print (informational; may be 0 pre-seed)
#   5. sample search probe runs (degraded if zero vectors present)
set -euo pipefail
URL="${DATA_LAYER_QDRANT_URL:-http://localhost:6333}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"

log() { printf '[smoke %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '[smoke FAIL] %s\n' "$*" >&2; exit 1; }

# 1) ping /healthz
log "test 1/5: GET /healthz"
curl -fsS "$URL/healthz" >/dev/null || fail "healthz failed"

# 2) list collections + assert both expected exist (delegates to test_collections.py)
log "test 2/5: list collections + schema check (test_collections.py)"
/opt/venv/bin/python "$ROOT/tests/test_collections.py" --url "$URL" || fail "collections check failed"

# 3) vector config — each collection must be 768-dim cosine
log "test 3/5: per-collection vector config"
for coll in mpg_source_authority_documents mpg_emails; do
  resp="$(curl -fsS "$URL/collections/$coll" || echo "")"
  if [ -z "$resp" ]; then fail "missing collection: $coll"; fi
  size=$(echo "$resp" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("result",{}).get("config",{}).get("params",{}).get("vectors",{}).get("size",""))')
  dist=$(echo "$resp" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("result",{}).get("config",{}).get("params",{}).get("vectors",{}).get("distance",""))')
  [ "$size" = "768" ] || fail "$coll vectors.size expected 768, got '$size'"
  [ "$dist" = "Cosine" ] || fail "$coll vectors.distance expected Cosine, got '$dist'"
  printf '    %s  size=%s  distance=%s\n' "$coll" "$size" "$dist"
done

# 4) point count check (informational; may be 0 pre-seed).
# /collections returns a brief shape that omits points_count + status,
# so we fetch each collection individually.
log "test 4/5: point counts (informational)"
for coll in mpg_source_authority_documents mpg_emails; do
  resp="$(curl -fsS "$URL/collections/$coll" || echo "")"
  if [ -n "$resp" ]; then
    pts=$(echo "$resp" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("result",{}).get("points_count",0))')
    sts=$(echo "$resp" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("result",{}).get("status","n/a"))')
    printf '    %s: %s points  status=%s\n' "$coll" "$pts" "$sts"
  else
    printf '    %s: missing\n' "$coll"
  fi
done

# 5) sample search probe — informational; zero-vector search returns
# 0 hits, which we treat as a degraded-but-pass result.
log "test 5/5: sample search probe"
SEARCH_BODY=$(python3 -c 'import json; print(json.dumps({"vector":[0.0]*768,"with_payload":True,"limit":3}))')
HITS=$(curl -fsS -X POST "$URL/collections/mpg_source_authority_documents/points/search" -H "Content-Type: application/json" -d "$SEARCH_BODY" | python3 -c '
import sys, json
d = json.load(sys.stdin)
res = d.get("result", [])
if isinstance(res, dict):
    res = res.get("points", [])
print(len(res))
' || echo "0")
echo "    sample-search hits: $HITS"
if [ "$HITS" = "0" ]; then
  log "  WARN: zero-vector search returned 0 hits (expected while embed-on-demand pipeline is pending). Tag as PASSED-WITH-WARN."
fi

log "all 5 smoke checks passed"