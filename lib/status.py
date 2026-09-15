#!/usr/bin/env python3
"""data-layer-qdrant/lib/status.py — print Qdrant version + collections."""
import argparse, json, sys, urllib.request, urllib.error


def http(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        body = r.read().decode()
        return r.status, json.loads(body) if body else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    base = args.url.rstrip("/")

    try:
        code, body = http(base)
        if code == 200 and isinstance(body, dict):
            print(f"  qdrant version: {body.get('version', '?')}")
    except urllib.error.URLError as e:
        print(f"  /  ERR: {e}")
        return 1

    try:
        code, body = http(base + "/collections")
    except urllib.error.URLError as e:
        print(f"  /collections ERR: {e}")
        return 1

    if code != 200 or not isinstance(body, dict):
        print(f"  collections: ERR {code}")
        return 1

    cols = body.get("result", {}).get("collections", [])
    if not cols:
        print("  collections: (none)")
    else:
        for c in cols:
            print(f"    - {c['name']}  points={c.get('points_count', 'n/a')}  status={c.get('status', 'n/a')}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
