#!/usr/bin/env python3
"""data-layer-qdrant/lib/qdrant.py — python helpers for Qdrant ops.

Subcommands (called by qdrant.sh or bootstrap):
  apply-collection  --url URL --name NAME --schema PATH  (idempotent)
  apply-migrations  --url URL --dir DIR                    (idempotent)
  delete-collection --url URL --name NAME
  delete-all-collections --url URL
  status            --url URL
"""
import argparse, glob, json, os, sys, urllib.request, urllib.error


def http(method, url, payload=None, timeout=30):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode()
            return r.status, json.loads(body) if body else None
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()


def cmd_apply_collection(args):
    with open(args.schema) as f:
        schema = json.load(f)
    url = f"{args.url.rstrip('/')}/collections/{args.name}"
    code, body = http("PUT", url, schema, args.timeout)
    print(f"  apply({args.name}) -> {code}")
    if code not in (200, 201):
        print(f"    body: {str(body)[:300]}")
        sys.exit(1)
    return 0


def cmd_apply_migrations(args):
    files = sorted(glob.glob(os.path.join(args.dir, "[0-9]*_*")))
    if not files:
        print(f"  no migration files in {args.dir}")
        return 0
    for f in files:
        with open(f) as fh:
            schema = json.load(fh)
        name = schema.get("collection_name")
        if not name:
            print(f"  skipping {f}: no collection_name")
            continue
        url = f"{args.url.rstrip('/')}/collections/{name}"
        # Idempotent: existing collection = no-op.
        get_code, _ = http("GET", url, None, args.timeout)
        if get_code == 200:
            print(f"  collection '{name}' already exists; skipping")
            continue
        code, body = http("PUT", url, schema, args.timeout)
        print(f"  apply({name}) -> {code}")
        if code not in (200, 201):
            print(f"    body: {str(body)[:300]}")
    return 0


def cmd_delete_collection(args):
    url = f"{args.url.rstrip('/')}/collections/{args.name}"
    code, _ = http("DELETE", url, None, args.timeout)
    print(f"  delete({args.name}) -> {code}")
    return 0


def cmd_delete_all_collections(args):
    code, body = http("GET", f"{args.url.rstrip('/')}/collections", None, args.timeout)
    if code != 200:
        print(f"  get collections -> {code}")
        return 1
    cols = (body or {}).get("result", {}).get("collections", [])
    if not cols:
        print("  no collections to delete")
        return 0
    for c in cols:
        d_code, _ = http("DELETE", f"{args.url.rstrip('/')}/collections/{c['name']}", None, args.timeout)
        print(f"  delete({c['name']}) -> {d_code}")
    return 0


def cmd_status(args):
    code, body = http("GET", args.url.rstrip("/"), None, args.timeout)
    if code == 200 and isinstance(body, dict):
        print(f"  qdrant version: {body.get('version', '?')}")
    code, body = http("GET", f"{args.url.rstrip('/')}/collections", None, args.timeout)
    if code == 200 and isinstance(body, dict):
        cols = body.get("result", {}).get("collections", [])
        if not cols:
            print("  collections: (none)")
        else:
            for c in cols:
                n = c.get("points_count", "n/a")
                st = c.get("status", "n/a")
                print(f"    - {c['name']}  points={n}  status={st}")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.environ.get("DATA_LAYER_QDRANT_URL", "http://localhost:6333"))
    ap.add_argument("--timeout", type=int, default=30)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("apply-collection")
    s.add_argument("--name", required=True)
    s.add_argument("--schema", required=True)
    s.set_defaults(func=cmd_apply_collection)
    s = sub.add_parser("apply-migrations")
    s.add_argument("--dir", required=True)
    s.set_defaults(func=cmd_apply_migrations)
    s = sub.add_parser("delete-collection")
    s.add_argument("--name", required=True)
    s.set_defaults(func=cmd_delete_collection)
    s = sub.add_parser("delete-all-collections")
    s.set_defaults(func=cmd_delete_all_collections)
    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)
    args = ap.parse_args()
    sys.exit(args.func(args) or 0)


if __name__ == "__main__":
    main()
