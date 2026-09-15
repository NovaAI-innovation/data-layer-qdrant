#!/usr/bin/env python3
"""data-layer-qdrant/migrations/apply_migrations.py — apply each
migrations/*.json to a running Qdrant. Idempotent (existing
collections are skipped). Used by docker-entrypoint.sh at first
boot and by bootstrap seed on demand.

Run:
    /opt/venv/bin/python migrations/apply_migrations.py
"""
import glob
import json
import os
import sys
import urllib.error
import urllib.request


URL = os.environ.get("DATA_LAYER_QDRANT_URL", "http://localhost:6333")
DIR = os.environ.get(
    "DATA_LAYER_MIGRATIONS_DIR",
    os.path.dirname(os.path.abspath(__file__)),
)


def apply(name, schema):
    url = f"{URL.rstrip('/')}/collections/{name}"
    try:
        with urllib.request.urlopen(url, timeout=10) as r:
            if r.status == 200:
                print(f"  {name}: exists, skipping")
                return 0
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print(f"  {name}: GET ERR {e.code}")
            return 1

    body = {k: v for k, v in schema.items() if k not in ("collection_name", "payload_schema")}
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            print(f"  {name}: created ({r.status})")
            return 0
    except urllib.error.HTTPError as e:
        body_bytes = e.read().decode()[:300] if e.fp else ""
        print(f"  {name}: PUT ERR {e.code} {e.reason} body={body_bytes}")
        return 1


def main():
    files = sorted(glob.glob(os.path.join(DIR, "[0-9]*_*.json")))
    if not files:
        print("  no migration files found")
        return 0
    rc = 0
    for f in files:
        with open(f) as fh:
            schema = json.load(fh)
        name = schema.get("collection_name")
        if not name:
            print(f"  skip {f}: no collection_name")
            continue
        rc |= apply(name, schema)
    return rc


if __name__ == "__main__":
    sys.exit(main())
