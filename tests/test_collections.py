#!/usr/bin/env python3
"""data-layer-qdrant/tests/test_collections.py — assert both expected
collections exist with correct vector config (768-dim cosine) and
report point counts + collection status.

The qdrant ``/collections`` list endpoint (1.19.x) returns a brief
shape ``[{"name": "..."}]`` that does NOT include ``points_count``,
``status``, or ``config``. We therefore fetch each collection
individually via ``/collections/{name}`` to get the full info.

Run:
    /opt/venv/bin/python tests/test_collections.py --url http://localhost:6333
"""
import argparse
import json
import sys
import urllib.error
import urllib.request


EXPECTED = {
    "mpg_source_authority_documents": {"size": 768, "distance": "Cosine"},
    "mpg_emails": {"size": 768, "distance": "Cosine"},
}


def http(url):
    with urllib.request.urlopen(url, timeout=10) as r:
        return r.status, json.loads(r.read().decode())


def fetch_collection(base, name):
    """GET /collections/{name}. Returns the parsed body or None on error."""
    try:
        code, body = http(base + "/collections/" + name)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise
    if code != 200 or not isinstance(body, dict):
        return None
    return body.get("result")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    args = ap.parse_args()
    base = args.url.rstrip("/")

    failures = []
    for name, want in EXPECTED.items():
        result = fetch_collection(base, name)
        if result is None:
            failures.append(f"missing collection: {name}")
            print(f"  {name}: MISSING")
            continue
        params = result.get("config", {}).get("params", {}).get("vectors", {})
        actual_size = params.get("size")
        actual_dist = params.get("distance")
        if actual_size != want["size"]:
            failures.append(
                f"{name}.vectors.size = {actual_size}, want {want['size']}"
            )
        if actual_dist != want["distance"]:
            failures.append(
                f"{name}.vectors.distance = {actual_dist}, want {want['distance']}"
            )
        print(
            f"  {name}: size={actual_size} distance={actual_dist} "
            f"status={result.get('status', 'n/a')} "
            f"points={result.get('points_count', 0)}"
        )

    if failures:
        print("  failures:")
        for f in failures:
            print(f"    - {f}")
        return 1
    print("  all expected collections present with correct vector config")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
