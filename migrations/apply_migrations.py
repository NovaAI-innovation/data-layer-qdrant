#!/usr/bin/env python3
"""data-layer-qdrant/migrations/apply_migrations.py - apply each
migrations/*.json to a running Qdrant. Idempotent (existing
collections are skipped). Used by docker-entrypoint.sh at first
boot and by `bash bootstrap apply-migrations` on demand.

After a successful create (PUT), the script re-GETs the live
collection and diffs ``config.params.vectors`` against the
specification. Drift (e.g. someone changed a collection's
``vectors.size`` out-of-band) is reported as WARN, not FAIL,
because re-running apply with the original spec will succeed
silently - qdrant PUT /collections/{name} does NOT update vector
size once points exist.

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


def http(method, path, payload=None, timeout=10):
    full = URL.rstrip("/") + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(full, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        return r.status, json.loads(body) if body else None


def desired_vectors(spec):
    """Extract the desired vectors spec from a migration JSON.

    Migration JSON shape (see 0001_*.json):
      { "collection_name": "...", "vectors": {"size": 768, "distance": "Cosine"}, ... }
    """
    v = spec.get("vectors") or {}
    return {"size": v.get("size"), "distance": v.get("distance")}


def verify_schema(name, expected):
    """GET /collections/{name} and diff config.params.vectors against expected.

    Returns (ok: bool, live: dict, message: str). ok=True means live
    config matches expected (or there are no expectations). ok=False
    means a drift was detected.
    """
    try:
        status, body = http("GET", "/collections/" + name)
    except urllib.error.HTTPError as e:
        return False, {}, "verification GET failed: HTTP " + str(e.code)
    except urllib.error.URLError as e:
        return False, {}, "verification GET failed: " + str(e)
    if status != 200 or not isinstance(body, dict):
        return False, {}, "verification GET returned status " + str(status)
    result = body.get("result") or {}
    params = result.get("config", {}).get("params", {}).get("vectors") or {}
    live = {"size": params.get("size"), "distance": params.get("distance")}
    expected_clean = {k: v for k, v in expected.items() if v is not None}
    if expected_clean and live != expected_clean:
        return False, live, (
            "DRIFT: expected " + json.dumps(expected_clean, sort_keys=True)
            + " but live is " + json.dumps(live, sort_keys=True)
        )
    return True, live, "schema matches"


def apply(name, schema):
    url_path = "/collections/" + name
    try:
        status, body = http("GET", url_path)
        if status == 200 and isinstance(body, dict):
            # Already exists - verify it matches the spec.
            expected = desired_vectors(schema)
            ok, live, msg = verify_schema(name, expected)
            drift_note = "" if ok else " [WARN: " + msg + "]"
            print("  " + name + ": exists, skipping" + drift_note)
            return 0 if ok else 2
    except urllib.error.HTTPError as e:
        if e.code != 404:
            print("  " + name + ": GET ERR " + str(e.code))
            return 1

    body = {k: v for k, v in schema.items() if k not in ("collection_name", "payload_schema")}
    try:
        status, resp = http("PUT", url_path, body)
        if status >= 400 or not isinstance(resp, dict):
            print("  " + name + ": PUT status " + str(status))
            return 1
        print("  " + name + ": created (" + str(status) + ")")
        # After-create verification catches drift introduced by manual edits.
        expected = desired_vectors(schema)
        ok, live, msg = verify_schema(name, expected)
        if not ok:
            print("    [WARN] post-create verification: " + msg)
            return 2
        print("    verified: vectors=" + json.dumps(live, sort_keys=True))
        return 0
    except urllib.error.HTTPError as e:
        body_bytes = e.read().decode()[:300] if e.fp else ""
        print("  " + name + ": PUT ERR " + str(e.code) + " " + str(e.reason) + " body=" + body_bytes)
        return 1


def main():
    files = sorted(glob.glob(os.path.join(DIR, "[0-9]*_*.json")))
    if not files:
        print("  no migration files found in " + DIR)
        return 0
    rc = 0
    for f in files:
        with open(f) as fh:
            schema = json.load(fh)
        name = schema.get("collection_name")
        if not name:
            print("  skip " + f + ": no collection_name")
            continue
        rc |= apply(name, schema)
    return rc


if __name__ == "__main__":
    sys.exit(main())
