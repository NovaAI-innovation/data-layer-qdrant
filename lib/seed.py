#!/usr/bin/env python3
"""data-layer-qdrant/lib/seed.py — idempotent seeder for source-authority docs.

For each row in the CSV:
- skip if do_not_ingest_y_n == 'Y'
- skip if sha256 missing/too short
- payload.lifecycle_status = 'superseded' if superseded_y_n == 'Y'
- point ID = md5(sha256).hexdigest()  (deterministic; same row -> same point)
- vector = [0.0] * 768 (placeholder until embed-on-demand attaches real vectors)

Idempotent on re-run (same rows -> same points, no duplicates).
"""
import argparse, csv, hashlib, json, sys, urllib.request, urllib.error


def http(method, url, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        return r.status, json.loads(body) if body else None


PAYLOAD_FIELDS = [
    "relative_path", "source_id", "source_family", "authority_class",
    "lifecycle_status", "governing_y_n", "reference_only_y_n",
    "superseded_y_n", "do_not_ingest_y_n",
    "proposed_retrieval_eligibility", "proposal_basis", "human_decision", "notes",
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--collection", required=True)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--vector-dim", type=int, default=768)
    args = ap.parse_args()

    put_url = f"{args.url.rstrip('/')}/collections/{args.collection}/points?wait=false"
    uploaded, skipped, batches = 0, 0, 0
    batch = []

    with open(args.csv, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sha = (row.get("sha256") or "").strip()
            if (row.get("do_not_ingest_y_n") or "").strip().upper() == "Y":
                skipped += 1
                continue
            if not sha or len(sha) < 16:
                skipped += 1
                continue
            sup = (row.get("superseded_y_n") or "").strip().upper() == "Y"
            payload = {k: (row.get(k) or "") for k in PAYLOAD_FIELDS}
            payload["lifecycle_status"] = "superseded" if sup else "active"
            payload["source_text"] = ((row.get("relative_path") or "") +
                                  " / " + (row.get("source_family") or ""))
            pid = hashlib.md5(sha.encode()).hexdigest()
            vec = [0.0] * args.vector_dim
            batch.append({"id": pid, "vector": vec, "payload": payload})
            uploaded += 1
            if len(batch) >= args.batch_size:
                code, body = http("PUT", put_url, {"points": batch}, args.batch_size and 60 or 60)
                batches += 1
                batch = []
        if batch:
            http("PUT", put_url, {"points": batch})
            batches += 1

    print(f"uploaded={uploaded} skipped={skipped} batches={batches}")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
