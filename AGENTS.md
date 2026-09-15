# AGENTS.md — data-layer-qdrant

Agent contract for the Qdrant-backed RAG layer of the Agent Zero
data-layer stack.

## Scope and ownership

This project owns the **vector search engine and embedding
infrastructure** for the data-layer stack. It does NOT own the
historical runtime record (that is `data-layer-postgres`), the
ephemeral knowledge cache (`data-layer-redis`), or the graph layer
(`data-layer-falkordb`).

Per the architecture you laid out:

| Submodule | Role |
| --- | --- |
| `data-layer-postgres` | historical runtime record |
| `data-layer-redis` | ephemeral knowledge |
| `data-layer-falkordb` | graph layer (nodes + edges tying it all together) |
| **`data-layer-qdrant`** | **RAG Source of Truth — Qdrant-backed vector store** |
| `data-layer-adapters` | framework adapters + **universal MCP that owns ALL agent retrieval tools** |

## Responsibility boundary

`data-layer-qdrant` is the SOT for **two collections**:

1. `mpg_source_authority_documents` — vectors for every file registered
   in the controlled-source-authority fixture (the corpus).
2. `mpg_emails` — vectors for every MPG email ingested (append-only).

Both collections share payload conventions (authority_class,
source_family, lifecycle_status, governing_y_n, retrieval_eligibility)
so the same `rag.search` filter vocabulary works across both.

`do_not_ingest_y_n = "Y"` and `superseded_y_n = "Y"` are blocking
columns enforced at write time AND at retrieval time. The
`rag.search` tool applies these filters unconditionally.

## Isolation and security

- This project is the **vector store layer** of the data-layer stack.
- Keep plans, scripts, docs, and evidence inside this workspace.
- Never write real secrets to source-controlled files; use
  `.env.example` for placeholders.
- Do not modify files in `/a0`, other projects, global plugins,
  system services, or live databases unless the user explicitly
  requests the integration and the side effect is reported.
- The DB-side `emails` table is owned by `data-layer-postgres`,
  NOT this project. The Qdrant side indexes into
  `mpg_emails` and references the postgres row UUID.
- The MCP server is owned by `data-layer-adapters`, NOT this
  project. This project provides the storage backend the MCP
  tools query against.

## Required workflow

Before consequential changes, read this file, `README.md`,
`.a0proj/instructions/project-isolation.md`, the dbss gap report
at `/a0/usr/workdir/dbss_gap_report/CKT-OC-047_...v01_DRAFT.md`,
the local build execution package at
`/a0/usr/workdir/mpg_dbss_build/MPG_SDD_DBSS_A0_LOCAL_BUILD_EXECUTION_PACKAGE_v01/`,
and the source-authority fixture at
`/a0/usr/workdir/MPG_DBSS_E2E_V03/MPG_DBSS_SOURCE_AUTHORITY_CONTROLLED_FIXTURE_v03.csv`.

State the intended outcome and affected paths before implementation.
Keep deployment state separate from source.

## Runtime boundary

- The Qdrant container / binary itself runs on the host (or in a
  Docker container orchestrated by the umbrella `docker-compose.yml`).
- Embedding model serving: `sentence-transformers/all-mpnet-base-v2`
  via `sentence-transformers` Python library (768-dim cosine)
  loaded directly. Alternative: `fastembed` for lighter weight.
- This project uses `/opt/venv/bin/python` for any internal scripts
  (migrations, ingestion).
- The MCP server (which calls into Qdrant) runs in
  `/opt/venv/bin/python`. Use `/opt/venv-a0/bin/python` for any
  Agent Zero framework or plugin-hook checks.
- Do not treat one runtime as proof of the other.

## Canonical references

- `README.md` — project overview + Qdrant collection model + integration points.
- `migrations/0001_collection_mpg_source_authority_documents.json` +
  `migrations/0002_collection_mpg_emails.json` — collection schemas
  applied by `migrations/apply_migrations.py`.
- `docs/decisions/0001-rag-sot-architecture.md` — ADR for the
  collection split, idempotency rules, gating policy.
- `bootstrap` — single dispatcher CLI (`install | verify | status
  | reset | seed`).
- `lib/install.sh` — bring up the Qdrant container (or configure
  the native binary install for session-only dev).
- `lib/qdrant.sh` — helper functions (qdrant_url, reachable,
  collection ops).
- `.env.example` — non-secret env template.
