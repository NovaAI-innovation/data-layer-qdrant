#!/usr/bin/env bash
# data-layer-qdrant/docker-entrypoint.sh
#
# Wraps the upstream `qdrant` entrypoint. On first boot:
#   1. Wait for Qdrant HTTP to be reachable (we don't apply migrations
#      until then — Qdrant itself is starting).
#   2. If /qdrant/migrations/apply_migrations.py exists, run it
#      against http://localhost:6333 (idempotent: skipped if
#      collections already exist with matching config).
#   3. If /qdrant/seeds/seed.py exists AND /qdrant/storage/.seeded
#      is absent, run it (one-shot bootstrap).
#   4. exec the original Qdrant entrypoint as PID 1.

set -euo pipefail

QDRANT_URL="${QDRANT_URL:-http://localhost:6333}"
QDRANT_BIN="${QDRANT_BIN:-/usr/local/bin/qdrant}"
APPLY_MIGRATIONS=/qdrant/migrations/apply_migrations.py
SEED_SCRIPT=/qdrant/seeds/seed.py
STORAGE_SEED_MARKER=/qdrant/storage/.seeded

log() { printf '[data-layer-qdrant entrypoint %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '[data-layer-qdrant FAIL] %s\n' "$*" >&2; exit 3; }

# 1. Wait for Qdrant HTTP.
log "waiting for Qdrant HTTP at $QDRANT_URL ..."
for i in $(seq 1 60); do
  if curl -fsS "$QDRANT_URL/healthz" >/dev/null 2>&1; then
    log "qdrant healthy after ${i}s"
    break
  fi
  if [ "$i" = "60" ]; then
    log "qdrant did not become healthy within 60s — proceeding anyway"
  fi
  sleep 1
done

# 2. Apply migrations if the script is present.
if [ -f "$APPLY_MIGRATIONS" ]; then
  log "applying migrations via $APPLY_MIGRATIONS"
  python3 "$APPLY_MIGRATIONS" --url "$QDRANT_URL" --collection mpg_source_authority_documents --schema /qdrant/migrations/0001_collection_mpg_source_authority_documents.json || log "migration 0001 returned non-zero (continuing)"
  python3 "$APPLY_MIGRATIONS" --url "$QDRANT_URL" --collection mpg_emails --schema /qdrant/migrations/0002_collection_mpg_emails.json || log "migration 0002 returned non-zero (continuing)"
else
  log "no $APPLY_MIGRATIONS — skipping"
fi

# 3. Seed if not already seeded.
if [ -f "$SEED_SCRIPT" ] && [ ! -f "$STORAGE_SEED_MARKER" ]; then
  log "seeding via $SEED_SCRIPT"
  if python3 "$SEED_SCRIPT" --url "$QDRANT_URL" \
       --csv "${DATA_LAYER_SOT_FIXTURE_CSV:-/qdrant/seeds/MPG_DBSS_SOURCE_AUTHORITY_CONTROLLED_FIXTURE.csv}" \
       --collection mpg_source_authority_documents; then
    : > "$STORAGE_SEED_MARKER"
    log "seed complete; marker written at $STORAGE_SEED_MARKER"
  else
    log "seed returned non-zero — leaving marker absent for retry"
  fi
else
  log "seed already done or no seed script — skipping"
fi

# 4. exec the original Qdrant entrypoint as PID 1.
log "exec $QDRANT_BIN $*"
exec "$QDRANT_BIN" "$@"
