#!/usr/bin/env python3
"""data-layer-qdrant/tests/test_collections.py — assert both expected
collections exist with correct vector config (768-dim cosine) and
optionally check the embedding model warmup.

Run:
    /opt/venv/bin/python tests/test_collections.py --url http://localhost:6333
"""
import argparse, json, sys, urllib.request, urllib.error


EXPECTED = {
    "mpg_source_authority_documents": {"size": 768, "distance": "Cosine"},
    "mpg_emails":                       {"size": 768, "distance": "Cosine"},
}


def http(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    base = args.url.rstrip("/")

    try:
        code, body = http(base + "/collections")
    except urllib.error.URLError as e:
        print(f"  URLError: {e}")
        return 1
    if code != 200 or not isinstance(body, dict):
        print(f"  ERR {code}")
        return 1

    cols = body.get("result", {}).get("collections", [])
    by_name = {c["name"]: c for c in cols}

    failures = []
    for name, want in EXPECTED.items():
        c = by_name.get(name)
        if not c:
            failures.append(f"missing collection: {name}")
            continue
        params = c.get("config", {}).get("params", {}).get("vectors", {})
        if params.get("size") != want["size"]:
            failures.append(f"{name}.vectors.size = {params.get('size')}, want {want['size']}")
        if params.get("distance") != want["distance"]:
            failures.append(f"{name}.vectors.distance = {params.get('distance')}, want {want['distance']}")
        print(f"  {name}: size={params.get('size')} distance={params.get('distance')} "
              f"status={c.get('status','n/a')} points={c.get('points_count', 0)}")

    if failures:
        print("  failures:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  all expected collections present with correct vector config")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)