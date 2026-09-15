# ADR 0001 — RAG SOT architecture (data-layer-qdrant)

**Status:** Proposed 2026-09-15
**Project:** data-layer-qdrant

## Context

The data-layer stack needs a vector store for the RAG-grounded agent
retrieval surface. Per the architecture you laid out:

| Layer | Role |
|---|---|
| `data-layer-postgres` | historical runtime record (immutable) |
| `data-layer-redis` | ephemeral knowledge cache |
| `data-layer-falkordb` | graph layer (nodes + edges tying layers together) |
| **`data-layer-qdrant` (this project)** | **RAG Source of Truth — vector store** |
| `data-layer-adapters` | universal MCP that owns ALL agent retrieval tools |

This ADR documents the design of the RAG layer.

## References (context inputs)

- `/a0/usr/workdir/dbss_gap_report/CKT-OC-047_MPG_DBSS_Repo_To_Functional_Build_Gap_Report_v01_DRAFT.md`
  — the gap report that identifies "Vectors stored external to
  SQLite per WP-04" as the missing piece. This project fills
  that role.
- `/a0/usr/workdir/MPG_DBSS_E2E_V03/MPG_DBSS_SOURCE_AUTHORITY_CONTROLLED_FIXTURE_v03.csv`
  — the 775-row controlled fixture that declares what may be
  ingested. Used by `lib/seed.py`.
- `/a0/usr/workdir/mpg_dbss_build/MPG_SDD_DBSS_A0_LOCAL_BUILD_EXECUTION_PACKAGE_v01/`
  — the local build execution package that defines the official
  ingestion procedure; this project's `bootstrap` script mirrors
  its shape (install | verify | status | reset | seed).
- `data-layer-adapters/docs/decisions/0001-dual-write-and-redis-publish-hook.md`
  — ADR for the dual-write contract on the WRITE side; this ADR
  complements it on the READ side (agent-facing retrieval).

## Decision

Two Qdrant collections, both 768-dim cosine, embedding model
`sentence-transformers/all-mpnet-base-v2`:

1. **`mpg_source_authority_documents`** — vectors for every file
   registered in the source-authority fixture CSV. Point ID =
   `md5(sha256).hexdigest()` so re-ingestion is idempotent.
2. **`mpg_emails`** — vectors for every MPG email ingested via the
   SMTP/IMAP gateway. Point ID = `data-layer-postgres.emails.id`
   (UUID). The payload carries the FK back to that row.

Both collections share the block-flag vocabulary
(`do_not_ingest_y_n`, `superseded_y_n`, etc.) so the same
`rag.search` payload-filter syntax works against both.

## Properties

- **Idempotent migrations** — `migrations/apply_migrations.py`
  walks `migrations/*.json` in order; existing collections are
  skipped on re-run.
- **Idempotent seeding** — `lib/seed.py` derives point IDs
  deterministically from sha256 (corpus) or postgres row UUID
  (emails). Re-runs are no-ops.
- **Block flags enforced at retrieval time** — every
  `rag.search` payload filter applies `do_not_ingest_y_n != 'Y'`
  and `superseded_y_n != 'Y'` unconditionally (defense in depth).
- **Block flags enforced at write time** — `lib/seed.py` skips
  `do_not_ingest_y_n = 'Y'` rows; superseded rows have
  `lifecycle_status = 'superseded'` (no new point created; the
  existing one is updated).
- **Embedding model is local** — `sentence-transformers` loaded
  into `/opt/venv`. No external API. The MCP, the
  embed-on-demand pipeline, and the seed script all use the same
  model.
- **MCP exposure** — the universal MCP at
  `data-layer-adapters/mcp/` exposes `rag.*` tools. Writes
  (`rag.ingest.point`, `rag.ingest.batch`) are gated by
  `MCP_INSTALL_MODE=1` (governed install-mode, NOT agent
  autonomy at runtime).
- **Postgres is the SOT for the email record** — Qdrant is
  derived from it. Every email row in
  `data-layer-postgres.emails` has a `qdrant_point_id` column
  tracked for traceability. Embedding is a derived index.

## Consequences

- The MCP is the agent-facing entry point; agents never write
  to Qdrant directly (they don't even have the network path in
  scope). The integration reduces to reads via the MCP, writes
  via the bootstrap scripts.
- A real embed-on-demand pipeline (replacing the current
  placeholder zero-vectors in `lib/seed.py`) is a follow-up;
  until then, semantic similarity degrades to a hash-based
  lookup over the controlled fixture. The placeholder doesn't
  block smoke tests (collections + vectors.size=768 + cosine
  all verified) but the user-visible semantic search will only
  become meaningful once the embedder is attached.
- The 768-dim vector must match across all collections and
  across the embedding model. Changing the embedding model
  requires a full reindex.
- A future ADR may add a `mpg_attachments` collection for email
  attachments; deferred for now.

## Decision log

- 2026-09-15: ADR drafted. Collection split finalized. Point ID
  scheme finalized. Idempotency rules finalized.
