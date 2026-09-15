#!/usr/bin/env bash
# data-layer-qdrant/lib/install.sh — bring up Qdrant.
# Mode: docker (preferred) or native (binary fallback)
set -euo pipefail
MODE="${1:-native}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." && pwd)"
log()  { printf '[qdrant.install %s] %s\n' "$(date +%H:%M:%S)" "$*"; }
fail() { printf '[qdrant.install FAIL] %s\n' "$*" >&2; exit 3; }

case "$MODE" in
  docker)
    if ! command -v docker >/dev/null 2>&1; then fail docker requested but missing; fi
    if [ ! -f "$ROOT/../docker-compose.yml" ]; then fail umbrella docker-compose.yml missing; fi
    ( cd "$ROOT/.." && docker compose up -d qdrant )
    log "waiting for /healthz ..."
    for i in $(seq 1 60); do
      curl -fsS http://localhost:6333/healthz >/dev/null 2>&1 && { log healthy after ${i}s; exit 0; }
      sleep 1
    done
    fail timeout
    ;;
  native)
    if [ ! -x /usr/local/bin/qdrant ]; then
      fail qdrant binary missing; download from github.com/qdrant/qdrant/releases
    fi
    mkdir -p /opt/qdrant/storage /opt/qdrant/snapshots /opt/qdrant/config
    [ -f /opt/qdrant/config/production.yaml ] || {
      cp "$ROOT/qdrant_config.yaml" /opt/qdrant/config/production.yaml
      log copied qdrant_config.yaml
    }
    if curl -fsS http://localhost:6333/healthz >/dev/null 2>&1; then
      log qdrant already running
    else
      nohup /usr/local/bin/qdrant --config-path /opt/qdrant/config/production.yaml >/var/log/qdrant.log 2>&1 &
      log "started qdrant PID=$!"
      for i in $(seq 1 30); do
        curl -fsS http://localhost:6333/healthz >/dev/null 2>&1 && { log healthy after ${i}s; exit 0; }
        sleep 1
      done
      fail timeout
    fi
    ;;
  *) fail unknown mode: $MODE ;;
esac
