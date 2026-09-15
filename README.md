# data-layer-qdrant

Qdrant-backed RAG (Retrieval-Augmented Generation) layer for the
Agent Zero data-layer stack. Holds the **MPG Source of Truth**:
authoritative corpus documents and ingested emails, plus their
vector embeddings for semantic search.

## Role in the data-layer stack

| Submodule | Role |
| --- | --- |
| `data-layer-postgres` | historical runtime record |
| `data-layer-redis` | ephemeral knowledge |
| `data-layer-falkordb` | graph layer (nodes + edges) |
| **`data-layer-qdrant`** | **RAG Source of Truth (this project)** |
| `data-layer-adapters` | framework adapters + universal MCP |

The MCP server in `data-layer-adapters/mcp/` exposes a unified
retrieval surface: 14 tools for the postgres read side, plus 7 tools
for the Qdrant read side. Tools in the rag.ingest.* group are
gated by the `MCP_INSTALL_MODE=1` env (writes are managed by the
bootstrap scripts, not by the agent at runtime).

## Collection model

### `mpg_source_authority_documents`

Vectors for every file registered in the MPG source-authority
controlled fixture. Point ID is the file's `sha256` (idempotent
re-ingestion).

Payload fields:
- `relative_path`, `sha256`, `source_id`, `source_family`,
  `authority_class`, `lifecycle_status`,
  `governing_y_n`, `reference_only_y_n`, `superseded_y_n`,
  `do_not_ingest_y_n`, `retrieval_eligibility`, `proposal_basis`,
  `human_decision`, `notes`, `source_text`

### `mpg_emails`

Vectors for every MPG email ingested. Point ID is the postgres row's
UUID. Payload carries the FK back to postgres plus filter fields.

Payload fields:
- `message_id`, `subject`, `from_email`, `to_emails`,
  `cc_emails`, `bcc_emails`, `body`, `received_at`, `in_reply_to`,
  `thread_id`, `project_id`, `agent_id`, `external_ref`

Both collections: 768-dim (sentence-transformers/all-mpnet-base-v2),
cosine distance.

## Layout

```
data-layer-qdrant/
├── AGENTS.md
├── README.md
├── .gitignore
├── .env.example
├── .a0proj/                 # Agent Zero project metadata
├── Dockerfile               # qdrant/qdrant:v1.x image
├── docker-entrypoint.sh     # applies migrations + seeds on first boot
├── qdrant_config.yaml       # service config mounted into the container
├── bootstrap                # install | verify | status | reset | seed
├── lib/                     # install.sh, qdrant.sh, seed.sh helpers
├── migrations/              # collection schemas + apply_migrations.py
├── seeds/                   # (optional) initial seed fixtures
├── tests/                   # smoke.sh + test_collections.py
├── docs/decisions/          # ADRs
└── requirements.txt         # qdrant-client, fastembed, sentence-transformers, pyyaml
```

## Configuration

```env
DATA_LAYER_QDRANT_URL=http://localhost:6333
DATA_LAYER_QDRANT_API_KEY=
COLLECTION_MPG_SOT=mpg_source_authority_documents
COLLECTION_MPG_EMAILS=mpg_emails
EMBEDDING_MODEL=sentence-transformers/all-mpnet-base-v2
EMBEDDING_DIM=768
```

## Quick start

### Docker (production path)

```bash
bash bootstrap install        # bring up Qdrant container
bash bootstrap status         # verify reachable, list collections
bash bootstrap seed          # idempotent ingest of source authority documents
bash bootstrap verify        # run smoke tests
```

### Native binary (dev / session workaround)

```bash
# One-time: download Qdrant binary
curl -L https://github.com/qdrant/qdrant/releases/latest/download/qdrant-x86_64-unknown-linux-gnu.tar.gz \
  | tar xz -C /tmp
cp /tmp/qdrant-*/qdrant /usr/local/bin/qdrant

# Create local storage + config dirs
mkdir -p /opt/qdrant/{storage,snapshots,config}

# Run natively
nohup /usr/local/bin/qdrant --config-path /opt/qdrant/config/production.yaml \
  >/var/log/qdrant.log 2>&1 &

# Verify
curl http://localhost:6333/healthz    # healthz check passed
curl http://localhost:6333/           # qdrant metadata JSON
```

## Integration points

| Endpoint | Used by |
| --- | --- |
| `POST /collections/{name}/points/search` | `rag.search` MCP tool |
| `GET /collections` | `rag.collections.list` MCP tool |
| `GET /collections/{name}` | `rag.collection.info` MCP tool |
| `PUT /collections/{name}/points` | `rag.ingest.point` (gated) |
| `GET /healthz` | `rag.health` MCP tool + smoke tests |

## Idempotency + gating

- **Reads** (`rag.search`, `rag.collections.list`, etc.) are
  always-on.
- **Writes** (`rag.ingest.point`, `rag.ingest.batch`) require
  `MCP_INSTALL_MODE=1` in the MCP server's environment. Without
  it, the MCP returns an error and does not contact Qdrant.
- The bootstrap scripts apply migrations + initial seed
  idempotently; point IDs are deterministic (sha256 for the
  corpus, UUID for emails) so re-runs are no-ops.

## Status: built + verified

After bring-up, `bash bootstrap verify` runs the smoke suite:

```
PING /healthz                              PASS
GET  /collections                          PASS (both expected)
GET  /collections/mpg_source_authority_documents  PASS (vector size 768)
GET  /collections/mpg_emails                PASS (vector size 768)
POST /collections/.../points/search        PASS (>=1 result)
```

See `tests/smoke.sh` for the full script.
