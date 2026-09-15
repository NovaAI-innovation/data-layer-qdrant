#!/usr/bin/env python3
"""data-layer-qdrant/lib/status.py — print Qdrant version + collections.

For each collection we fetch ``/collections/{name}`` because the
``/collections`` list endpoint (1.19.x) returns only ``[{"name": "..."}]``
and does NOT include ``points_count``, ``status``, or ``config``.
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


def http(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        body = r.read().decode()
        return r.status, json.loads(body) if body else None


def fetch(base, path):
    try:
        code, body = http(base + path)
        return code, body
    except urllib.error.URLError as e:
        return 0, {"error": str(e)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    base = args.url.rstrip("/")

    code, body = fetch(base, "/")
    if code == 200 and isinstance(body, dict):
        print("  qdrant version: " + str(body.get("version", "?")))
    else:
        print("  /  ERR: " + repr(body))
        return 1

    code, body = fetch(base, "/collections")
    if code != 200 or not isinstance(body, dict):
        print("  /collections ERR: " + repr(body))
        return 1

    cols = body.get("result", {}).get("collections", [])
    if not cols:
        print("  collections: (none)")
        return 0

    for c in cols:
        name = c.get("name")
        if not name:
            continue
        # Fetch the per-collection endpoint to get full info.
        ccode, cbody = fetch(base, "/collections/" + name)
        if ccode == 200 and isinstance(cbody, dict) and "result" in cbody:
            r = cbody["result"]
            print(
                "    - " + name
                + "  points=" + str(r.get("points_count", "n/a"))
                + "  status=" + str(r.get("status", "n/a"))
                + "  vectors.size=" + str(
                    r.get("config", {}).get("params", {}).get("vectors", {}).get("size", "n/a")
                )
            )
        else:
            print(
                "    - " + name
                + "  points=n/a  status=n/a  (fetch failed)"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
