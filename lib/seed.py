#!/usr/bin/env python3
"""data-layer-qdrant/lib/seed.py - idempotent seeder for source-authority docs.

Reads a CSV where each row has sha256, do_not_ingest_y_n, superseded_y_n
plus the source-authority columns. For each row:
  * skip if do_not_ingest_y_n == 'Y'
  * skip if sha256 missing/too short
  * payload.lifecycle_status = 'superseded' if superseded_y_n == 'Y',
    else 'active'
  * point ID = md5(sha256).hexdigest() (deterministic; same row -> same point)
  * vector = [0.0] * vector_dim (placeholder until embed-on-demand
    attaches real vectors)

Idempotent on re-run (same rows -> same points, no duplicates).

After a successful run, writes a small JSON marker file at
DATA_LAYER_QDRANT_INGEST_MARKER (default
/opt/qdrant/state/last_ingest.json) so the MCP rag.ingest.status
tool can report what the last seed actually did. The marker write
is best-effort: failures are logged but do NOT abort the seed.
"""
import argparse
import csv
import datetime
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request


PAYLOAD_FIELDS = [
    "relative_path", "source_id", "source_family", "authority_class",
    "lifecycle_status", "governing_y_n", "reference_only_y_n",
    "superseded_y_n", "do_not_ingest_y_n",
    "proposed_retrieval_eligibility", "proposal_basis", "human_decision", "notes",
]

DEFAULT_MARKER_PATH = os.environ.get(
    "DATA_LAYER_QDRANT_INGEST_MARKER",
    "/opt/qdrant/state/last_ingest.json",
)


def http(method, url, payload=None, timeout=60):
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read().decode()
        return r.status, json.loads(body) if body else None


def write_marker(marker_path, summary):
    try:
        marker_dir = os.path.dirname(marker_path)
        if marker_dir and not os.path.isdir(marker_dir):
            os.makedirs(marker_dir, exist_ok=True)
        with open(marker_path, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, sort_keys=True)
        print("marker written: " + marker_path)
    except OSError as e:
        # Don't fail the seed for an observability marker write.
        print("marker write skipped: " + type(e).__name__ + ": " + str(e))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--collection", required=True)
    ap.add_argument("--batch-size", type=int, default=64)
    ap.add_argument("--vector-dim", type=int, default=768)
    ap.add_argument(
        "--marker-path",
        default=DEFAULT_MARKER_PATH,
        help=(
            "Path to the JSON marker file the MCP rag.ingest.status tool "
            "reads. Default: $DATA_LAYER_QDRANT_INGEST_MARKER or "
            "/opt/qdrant/state/last_ingest.json"
        ),
    )
    ap.add_argument(
        "--wait",
        choices=("true", "false"),
        default="true",
        help=(
            "Pass '?wait=true' to qdrant PUT: blocks until the server "
            "has indexed the batch (slower but deterministic counts). "
            "Default true. Use false only for fast bulk ingest where "
            "imprecise point-count timing is acceptable."
        ),
    )
    ap.add_argument(
        "--embed",
        choices=("auto", "on", "off"),
        default="auto",
        help=(
            "Embedding mode. 'auto' = use the real sentence-transformers "
            "encoder if DATA_LAYER_QDRANT_EMBED=1 AND sentence-transformers "
            "is importable, else fall back to [0.0] * vector_dim "
            "placeholders. 'on' = require the encoder (fail loudly if "
            "missing). 'off' = always use placeholders."
        ),
    )
    args = ap.parse_args()

    # Resolve embedding mode. Default is zero-vector placeholders (the
    # historical behavior; smoke tests + ad-hoc ingestion still work
    # without the 400MB sentence-transformers model installed).
    use_embed = False
    encoder = None
    if args.embed == "on":
        use_embed = True
    elif args.embed == "auto":
        use_embed = os.environ.get("DATA_LAYER_QDRANT_EMBED", "") == "1"
    if use_embed:
        try:
            from embed import get_encoder  # type: ignore
            encoder = get_encoder()
            log("embed mode: ON (sentence-transformers/all-mpnet-base-v2)")
        except Exception as e:
            if args.embed == "on":
                fail("embed=on but encoder unavailable: " + str(e))
            log(
                "embed mode: requested but encoder unavailable "
                "(" + str(e) + "); falling back to [0.0] * "
                + str(args.vector_dim) + " placeholders"
            )
            use_embed = False
            encoder = None
    if not use_embed:
        log(
            "embed mode: OFF (placeholder zero-vectors; set "
            "DATA_LAYER_QDRANT_EMBED=1 + pip install "
            "sentence-transformers to enable real embeddings)"
        )

    put_url = (
        args.url.rstrip("/")
        + "/collections/" + args.collection
        + "/points?wait=" + args.wait
    )
    uploaded, skipped, batches = 0, 0, 0
    batch = []
    started_at = time.time()

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
            payload["source_text"] = (
                (row.get("relative_path") or "")
                + " / "
                + (row.get("source_family") or "")
            )
            pid = hashlib.md5(sha.encode()).hexdigest()
            if use_embed:
                # source_text is the human-readable concatenation of
                # relative_path + source_family (set at lines 120-124
                # above). The encoder produces 768-dim cosine vectors.
                vec = encoder.encode(payload["source_text"])
            else:
                vec = [0.0] * args.vector_dim
            batch.append({"id": pid, "vector": vec, "payload": payload})
            uploaded += 1
            if len(batch) >= args.batch_size:
                http("PUT", put_url, {"points": batch}, timeout=60)
                batches += 1
                batch = []
        if batch:
            http("PUT", put_url, {"points": batch}, timeout=60)
            batches += 1

    duration_s = round(time.time() - started_at, 3)
    print(
        "uploaded=" + str(uploaded)
        + " skipped=" + str(skipped)
        + " batches=" + str(batches)
        + " wait=" + str(args.wait)
        + " duration_s=" + str(duration_s)
    )

    # Best-effort marker write so the MCP rag.ingest.status tool can
    # report the actual last ingest.
    write_marker(args.marker_path, {
        "collection": args.collection,
        "csv": args.csv,
        "uploaded": uploaded,
        "skipped": skipped,
        "batches": batches,
        "wait": args.wait == "true",
        "vector_dim": args.vector_dim,
        "duration_s": duration_s,
        "timestamp_utc": datetime.datetime.now(datetime.UTC).isoformat().replace("+00:00", "Z") + "Z",
    })
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
