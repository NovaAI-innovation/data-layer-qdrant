# data-layer-qdrant — SCHEMAS.md

**Qdrant is the derived semantic index for the RAG SOT layer of the
data-layer stack**, per `docs/SUBMODULE_OWNERSHIP.md` boundary rule
#1 (no cross-submodule imports) and rule #4 (MCP exposes reads; writes
go through bootstrap scripts). Per ADR
`docs/decisions/0001-rag-sot-architecture.md`, this document is the
column-level payload schema spec for the two Qdrant collections
introduced by migrations `0001_collection_mpg_source_authority_documents.json`
and `0002_collection_mpg_emails.json`. Every payload field is
documented along five dimensions:

1. **Purpose** — what the field represents.
2. **Value** — what the field enables at the agent / operator level.
3. **Retrieval impact** — how the field is used by MCP read tools
   (`rag.search`, `rag.collection.info`, `rag.collections.list`) and
   by the `lib/status.py` smoke checks.
4. **Mutation / transformation impact** — how writes and derived
   fields (e.g. corpus `source_text` → 768-dim vector) propagate
   downstream.
5. **Queries enabled** — concrete Qdrant payload-filter patterns this
   field makes efficient (i.e. backed by a payload index).

> **Schema authority rule:** if this doc disagrees with the migration
> `.json` file, the migration wins. Update this doc in the same
> commit that updates the schema.

---

## Collection inventory (2 collections)

| # | Collection | Migration | Source of truth | Cardinality expectation |
|---|---|---|---|---|
| 1 | `mpg_source_authority_documents` | `0001_collection_mpg_source_authority_documents.json` | the controlled-source-authority CSV fixture (`DATA_LAYER_SOT_FIXTURE_CSV`) — 775 rows | hundreds → low thousands |
| 2 | `mpg_emails` | `0002_collection_mpg_emails.json` | `data-layer-postgres.emails` (FK via `qdrant_point_id`) | append-only; bounded by inbound email volume |

Both collections are 768-dim cosine vectors, encoded by
`sentence-transformers/all-mpnet-base-v2` loaded into the
`/opt/venv` Python runtime.

---

## Common contract (applies to BOTH collections)

These invariants bind the two collections together. Per ADR 0001
"Properties", any change to the items below is a reindex event.

### Vector spec

- **Embedding model:** `sentence-transformers/all-mpnet-base-v2`
  (env override: `DATA_LAYER_QDRANT_EMBED_MODEL`).
- **Vector size:** 768 (`EXPECTED_DIM` in `lib/embed.py`;
  `EMBEDDING_DIM=768` in `.env.example`).
- **Distance:** `Cosine` (`vectors.distance: Cosine` in every
  migration JSON).
- **Encoding path:** `lib/embed.py` → `Encoder.encode()` → 768-float
  list. Default embedding mode is `auto` (zero-vector placeholders
  unless `DATA_LAYER_QDRANT_EMBED=1` AND `sentence-transformers` is
  importable); `on` requires the encoder (fails loudly if missing);
  `off` always uses placeholders.

### Point ID scheme

| Collection | Point ID | Derivation |
|---|---|---|
| `mpg_source_authority_documents` | `md5(sha256).hexdigest()` | deterministic; re-ingestion of the same row → same point (no duplicates) |
| `mpg_emails` | `data-layer-postgres.emails.id` (UUID) | the postgres row UUID is the Qdrant point id verbatim; the payload carries the same UUID as `qdrant_point_id` for traceability |

Per ADR 0001, both derivations are idempotent: re-running `seed.py`
or `mail_replay.py` against the same source rows is a no-op.

### HNSW + optimizer + quantization (shared config)

From both migration JSONs (verbatim):

| Setting | Value | Source |
|---|---|---|
| `hnsw_config.m` | 16 | migration JSON `hnsw_config` |
| `hnsw_config.ef_construct` | 100 | migration JSON `hnsw_config` |
| `hnsw_config.full_scan_threshold` | 10000 | migration JSON `hnsw_config` |
| `optimizer_config.indexing_threshold` | 20000 | migration JSON `optimizer_config` |
| `quantization_config.scalar.type` | `int8` | migration JSON `quantization_config` |
| `quantization_config.scalar.quantile` | 0.99 | migration JSON `quantization_config` |
| `quantization_config.scalar.always_ram` | false | migration JSON `quantization_config` |

`qdrant_config.yaml` mirrors these in the `collection_defaults`
block (with `indexing_threshold: 2000` for dev tuning — the
migration JSON is authoritative).

### Allowlist gate (MCP-side)

The MCP server in `data-layer-adapters/mcp/` accepts writes
(`rag.ingest.point`, `rag.ingest.batch`) only against collection
names that appear in its allowlist. Per ADR 0001 + SUBMODULE_OWNERSHIP.md
rule #4, the allowlist contains exactly:

- `mpg_source_authority_documents`
- `mpg_emails`

Any other collection name returns an MCP-side rejection before the
HTTP call is made to Qdrant.

### MCP_INSTALL_MODE gate (write-side)

The two `rag.ingest.*` tools (`rag.ingest.point`, `rag.ingest.batch`)
require `MCP_INSTALL_MODE=1` in the MCP server's environment. Without
that env var the MCP returns an error and does not contact Qdrant.
This is the runtime-side enforcement of SUBMODULE_OWNERSHIP.md
rule #4: writes go through bootstrap scripts (`lib/seed.py`,
`lib/mail_replay.py`), not through agent-driven tool calls.

### Always-on SOT filters (read-side enforcement)

Every `rag.search` call applies the following payload filters
unconditionally (defense in depth per ADR 0001 "Properties"):

```
do_not_ingest_y_n != 'Y'   AND   superseded_y_n != 'Y'
```

For the corpus collection, the second filter is equivalently
expressed as `lifecycle_status != 'superseded'` (set by
`lib/seed.py` at write time). For `mpg_emails` the
`do_not_ingest_y_n` / `superseded_y_n` vocabulary does not exist
on the qdrant side — the read-side filter is enforced upstream
in `data-layer-postgres.emails.qdrant_ingested_y_n`
(see Cross-layer joins below).

---

## Collection 1 — `mpg_source_authority_documents`

Source-of-truth: the controlled-source-authority CSV fixture
referenced in ADR 0001 (default path
`/a0/usr/workdir/MPG_DBSS_E2E_V03/MPG_DBSS_SOURCE_AUTHORITY_CONTROLLED_FIXTURE_v03.csv`,
env `DATA_LAYER_SOT_FIXTURE_CSV`). Each row of the CSV becomes one
Qdrant point.

### 1a. Point ID scheme + derivation

- **Formula:** `pid = hashlib.md5(row.sha256.encode()).hexdigest()`
  (see `lib/seed.py` line ~176).
- **Length:** 32 hex chars (MD5 hex digest).
- **Stability:** deterministic — the same CSV row always produces the
  same point id. Re-running `seed.py` is a no-op (no duplicates).
- **Drift invariant:** if the same `sha256` appears with different
  payload values, `PUT /collections/{name}/points?wait=true` updates
  the existing point in place (the upsert is id-keyed, not content-
  keyed).
- **Cross-link:** the `md5(sha256).hexdigest()` value is recorded
  as `corpus.qdrant_point_id` in any downstream tooling that needs
  to map a Qdrant hit back to its source-authority CSV row.

### 1b. Payload fields (15 fields)

| Field | Type | Purpose | Value | Retrieval impact | Mutation | Queries enabled |
|---|---|---|---|---|---|---|
| `relative_path` | `text` | source file path within the corpus (e.g. `MPG_SDD_DBSS/.../0001_init.sql`) | human-readable locator; surfaced in search hits | `rag.search` returns the path in payload; `rag.collection.info` reports total distinct paths | immutable per point (id is content-derived) | equality + `match` payload filter |
| `sha256` | `text` | content hash of the source file | content identity for audit + dedupe | surfaced in payload for audit trails; used to verify the point id derivation | immutable; the point id is `md5(sha256)` so the hash is the canonical key | equality |
| `source_id` | `text` | upstream registry id (from the CSV) | cross-system join key into the source-authority registry | surfaced in payload; join target for graph-layer (`data-layer-falkordb`) enrichment | immutable per CSV row | equality |
| `source_family` | `text` | corpus family grouping (e.g. `MPG_SDD_DBSS`, `MPG_CKT`) | high-level taxonomy for filtered search | filter by family in `rag.search`; surfaced in results | immutable per CSV row | equality + term match |
| `authority_class` | `text` | classification of authority weight (e.g. `governing`, `reference`, `proposed`) | governance signal for retrieval weighting | ranked filter: `authority_class IN ('governing')`; surfaced in payload | mutable (governance changes update payload) | equality + `IN` |
| `lifecycle_status` | `keyword` | derived — `'active'` or `'superseded'` | runtime gate | **read-side filter target**: `lifecycle_status != 'superseded'` (always-on); also surfaced in results | derived in `lib/seed.py` from `superseded_y_n` column; transitions on supersede event | equality + `IN` + index |
| `governing_y_n` | `keyword` | `'Y'` / `''` flag — is this a governing document? | governance gate | filter `governing_y_n = 'Y'` to scope to governing docs only | mutable (governance transitions) | equality |
| `reference_only_y_n` | `keyword` | `'Y'` / `''` flag — reference-only (not governing) | inverse of governing flag | filter `reference_only_y_n = 'Y'` for non-governing retrieval | mutable | equality |
| `superseded_y_n` | `keyword` | `'Y'` / `''` flag — has this been superseded? | supersede gate | **read-side filter target**: `superseded_y_n != 'Y'` (always-on); also drives `lifecycle_status` | mutable (supersede → write-time update, not new point per ADR 0001) | equality + index |
| `do_not_ingest_y_n` | `keyword` | `'Y'` / `''` flag — must never be ingested/retrieved | hard block | **read-side filter target**: `do_not_ingest_y_n != 'Y'` (always-on); also write-time skip in `lib/seed.py` | mutable (transition `'Y'` → `''` requires a re-seed) | equality + index |
| `proposed_retrieval_eligibility` | `text` | proposed eligibility tier (from CSV) | staged eligibility change before `authority_class` | filter on the proposed value during the proposal phase | mutable (proposal → governance) | equality + `match` |
| `proposal_basis` | `text` | rationale for the proposed eligibility | audit trail | surfaced in payload for human-decision support | mutable until decision recorded | `match` + ILIKE |
| `human_decision` | `text` | final human decision (approve / reject / defer) | audit + supersede-trigger signal | surfaced in payload; `human_decision = 'superseded'` correlates with `superseded_y_n='Y'` | mutable; immutable once `'superseded'` | equality + `match` |
| `notes` | `text` | free-form operator notes | operator context | surfaced in payload (not used for filtering) | mutable | `match` + ILIKE |
| `source_text` | `text` | derived embedding-source string — `relative_path + ' / ' + source_family` | the string the encoder actually vectorizes | NOT surfaced in payload (kept on the corpus side for the encoder's `encode()` call); the 768-dim vector is what retrieval matches against | re-derived in `lib/seed.py` on every row from `relative_path` + `source_family` | n/a (derived; not queried) |

### 1c. Always-on SOT filters (read-side enforcement)

Per ADR 0001, every `rag.search` against `mpg_source_authority_documents`
applies:

```
do_not_ingest_y_n != 'Y'   AND   superseded_y_n != 'Y'
```

The second filter is enforced equivalently via
`lifecycle_status != 'superseded'` because `lib/seed.py` sets
`lifecycle_status = 'superseded'` whenever `superseded_y_n = 'Y'`
in the CSV. This is defense in depth: even if one column is
desynchronized, the other blocks retrieval.

### 1d. Write-time SOT invariants (`lib/seed.py`)

- **Hard skip:** if `do_not_ingest_y_n = 'Y'` the row is skipped
  entirely — no point is created, no payload is written
  (`lib/seed.py` line ~162). This is the only path through which
  `do_not_ingest_y_n` becomes binding.
- **Supersede = update, not insert:** if `superseded_y_n = 'Y'` the
  row is still ingested but with `payload.lifecycle_status =
  'superseded'` (`lib/seed.py` line ~170). The point id remains
  `md5(sha256).hexdigest()` — re-deriving the same id from the same
  sha256 means a supersede event is an upsert into the existing
  point, never a new point.
- **Missing sha256:** if `sha256` is empty or shorter than 16 chars
  the row is skipped (`lib/seed.py` line ~165).
- **Batch boundaries:** rows are batched at `--batch-size` (default
  64); each batch is a single `PUT /collections/{name}/points?wait=...`
  call.
- **Wait semantics:** `--wait=true` (default) blocks until the
  server has indexed the batch (slower but deterministic point
  counts); `--wait=false` is faster but imprecise for point-count
  observability.

---

## Collection 2 — `mpg_emails`

Source-of-truth: `data-layer-postgres.emails` (migration
`0007_emails.sql`). Each row of that table is mirrored into one
Qdrant point. The MCP / `lib/mail_replay.py` writes go through
postgres first (durable) then upsert into qdrant (derived).

### 2a. Point ID scheme + derivation

- **Formula:** `pid = str(emails.id)` — the postgres row UUID is the
  Qdrant point id verbatim.
- **Type:** UUID string (e.g. `550e8400-e29b-41d4-a716-446655440000`).
- **Stability:** durable — as long as the postgres row exists, the
  point id is stable. `DELETE` in postgres must be paired with a
  Qdrant delete (out of scope for the current scripts; the
  `data-layer-postgres.emails.qdrant_ingested_y_n` column tracks
  the mirror state).
- **Cross-link:** the same UUID is mirrored back into
  `data-layer-postgres.emails.qdrant_point_id` (UNIQUE column on
  the postgres side) so a postgres row can be located from a
  Qdrant hit and vice versa.

### 2b. Payload fields (13 fields)

| Field | Type | Purpose | Value | Retrieval impact | Mutation | Queries enabled |
|---|---|---|---|---|---|---|
| `message_id` | `text` | RFC 5322 `Message-ID:` header | cross-system message identity (also the inbox-dedupe key in postgres) | surfaced in payload; join key for email gateways | immutable; UNIQUE in postgres | equality + `match` |
| `subject` | `text` | email subject line | human-readable thread topic | surfaced in payload; ILIKE-style match for fuzzy subject search | immutable (RFC mail headers are immutable per row) | equality + `match` |
| `from_email` | `text` | RFC 5322 `From:` address | sender identity | surfaced in payload; `from_email = '...'` filter | immutable | equality + `match` |
| `to_emails` | `text` | RFC 5322 `To:` recipients (JSON-encoded list) | recipient scope | surfaced as a JSON string; JSONB containment-style queries in payload filters | immutable | equality + `contains` |
| `cc_emails` | `text` | RFC 5322 `Cc:` recipients (JSON-encoded list) | cc scope | surfaced as a JSON string | immutable | equality + `contains` |
| `bcc_emails` | `text` | RFC 5322 `Bcc:` recipients (JSON-encoded list) | bcc scope (rare; usually empty for inbound) | surfaced as a JSON string | immutable | equality + `contains` |
| `body` | `text` | plain-text body (extracted by `mail_replay.py`) | the string the encoder vectorizes | **the primary retrieval target**: the 768-dim vector is `Encoder.encode(body)`; payload `body` is surfaced in search hits | immutable once ingested (re-ingest updates in place via id-keyed upsert) | `match` + ILIKE |
| `received_at` | `keyword` | RFC 5322 `Date:` header (ISO 8601 string) | wall-clock arrival time | surfaced in payload; range filter via payload `range` queries | immutable | equality + range (`lt` / `gt`) + index |
| `in_reply_to` | `text` | RFC 5322 `In-Reply-To:` header | thread-construction join key | filter `in_reply_to = '...'` to find replies in a thread | immutable | equality + `match` |
| `thread_id` | `keyword` | derived — UUID linking the conversation (from postgres) | thread group | filter by `thread_id` to scope search to one thread | mutable (recomputed if `in_reply_to` chain is re-walked) | equality + index |
| `project_id` | `keyword` | `data-layer-postgres.projects.id` (UUID) | tenant scope | filter by `project_id` for multi-tenant retrieval; mirrors the postgres FK | mutable (if the postgres row's `project_id` changes, the qdrant payload must be updated too) | equality + index |
| `agent_id` | `keyword` | `data-layer-postgres.agents.id` (UUID) | originating / recipient agent identity | filter by `agent_id` for per-agent email search | mutable (reassigned if the postgres FK changes) | equality + index |
| `external_ref` | `text` | external reference id (e.g. IMAP UID, gateway correlation id) | cross-system correlation | surfaced in payload; join into `data-layer-postgres.emails.external_ref` | immutable (UNIQUE-ish in the gateway log) | equality + `match` |

### 2c. Always-on SOT filters (read-side enforcement)

`mpg_emails` does NOT carry `do_not_ingest_y_n` or `superseded_y_n`
on the Qdrant payload — those gates live on the postgres side as
`data-layer-postgres.emails.qdrant_ingested_y_n`
(CHECK constraint `'Y'`, `'N'`, `'SUPERSEDED'`, `'DO_NOT_INGEST'`,
see `data-layer-postgres/SCHEMAS.md` §13).

The read-side enforcement is therefore upstream of the qdrant
read: `rag.search` against `mpg_emails` is paired with a postgres
filter on `qdrant_ingested_y_n = 'Y'`. For the supersede path, the
postgres row is transitioned to `qdrant_ingested_y_n = 'SUPERSEDED'`
and the qdrant payload is updated in place (no new point).

### 2d. Write-time SOT invariants (`lib/mail_replay.py`)

- **Dual-write contract:** for every mbox message,
  `lib/mail_replay.py` first `INSERT`s into
  `data-layer-postgres.emails` (UNIQUE constraint on `message_id`
  provides idempotency via `ON CONFLICT (message_id) DO NOTHING`),
  then upserts the same row into `mpg_emails` via direct HTTP PUT.
- **Status mirroring:** `postgres.emails.qdrant_ingested_y_n` is
  set to `'Y'` on qdrant upsert success, `'N'` on qdrant failure.
- **Idempotent re-run:** because the `message_id` UNIQUE constraint
  blocks the postgres INSERT on re-run, the qdrant upsert is
  skipped automatically.
- **Dry-run mode:** `--dry-run` parses + prints without writing
  (postgres or qdrant).
- **MCP path:** the bootstrap-side script above is the governed
  write path. The agent-facing path is `rag.ingest.point` /
  `rag.ingest.batch`, gated by `MCP_INSTALL_MODE=1`.

---

## Cross-layer joins

This section pins every `qdrant_point_id` ↔ postgres column / CSV row
relationship so a Qdrant hit can be reverse-resolved into the SOT.

### A. `mpg_emails` ↔ `data-layer-postgres.emails`

| Qdrant (this project) | Postgres (`data-layer-postgres/SCHEMAS.md` §13) |
|---|---|
| `mpg_emails` point id (UUID) | `emails.id` (UUID PK) |
| payload `message_id` | `emails.message_id` (UNIQUE) |
| payload `subject` | `emails.subject` |
| payload `from_email` | `emails.from_email` |
| payload `to_emails` (JSON string) | `emails.to_emails` (jsonb) |
| payload `cc_emails` (JSON string) | `emails.cc_emails` (jsonb) |
| payload `bcc_emails` (JSON string) | `emails.bcc_emails` (jsonb) |
| payload `body` | `emails.body` |
| payload `received_at` (keyword) | `emails.received_at` (timestamptz; ISO 8601 string in payload) |
| payload `in_reply_to` | `emails.in_reply_to` (self-FK) |
| payload `thread_id` | `emails.thread_id` |
| payload `project_id` | `emails.project_id` (FK → `projects.id`) |
| payload `agent_id` | `emails.agent_id` (FK → `agents.id`) |
| payload `external_ref` | `emails.external_ref` (jsonb) |
| n/a (no qdrant side) | `emails.qdrant_point_id` (UNIQUE) — the reverse link; populated to mirror `emails.id` |
| n/a (no qdrant side) | `emails.qdrant_ingested_y_n` — gate column that drives the read-side filter |

**Resolution rule:** given a Qdrant hit id `H`, the corresponding
postgres row is `SELECT * FROM emails WHERE id = 'H';`. Given a
postgres row, the corresponding Qdrant point id is
`emails.qdrant_point_id`.

### B. `mpg_source_authority_documents` ↔ source-authority CSV row

| Qdrant (this project) | CSV row |
|---|---|
| `mpg_source_authority_documents` point id | `md5(row.sha256).hexdigest()` |
| payload `sha256` | CSV `sha256` column |
| payload `relative_path` | CSV `relative_path` column |
| payload `source_id` | CSV `source_id` column |
| payload `source_family` | CSV `source_family` column |
| payload `authority_class` | CSV `authority_class` column |
| payload `governing_y_n` | CSV `governing_y_n` column |
| payload `reference_only_y_n` | CSV `reference_only_y_n` column |
| payload `superseded_y_n` | CSV `superseded_y_n` column |
| payload `do_not_ingest_y_n` | CSV `do_not_ingest_y_n` column |
| payload `proposed_retrieval_eligibility` | CSV `proposed_retrieval_eligibility` column |
| payload `proposal_basis` | CSV `proposal_basis` column |
| payload `human_decision` | CSV `human_decision` column |
| payload `notes` | CSV `notes` column |
| payload `lifecycle_status` | derived (not in CSV): `'superseded'` if `superseded_y_n='Y'`, else `'active'` |
| payload `source_text` | derived (not in CSV): `relative_path + ' / ' + source_family` |

**Resolution rule:** given a Qdrant hit id `H`, the corresponding
CSV row is the one whose `md5(sha256.encode()).hexdigest() == H`.
The CSV is the controlled fixture at
`DATA_LAYER_SOT_FIXTURE_CSV`
(default `/a0/usr/workdir/MPG_DBSS_E2E_V03/MPG_DBSS_SOURCE_AUTHORITY_CONTROLLED_FIXTURE_v03.csv`,
775 rows).

---

## Pipeline scripts

Every script in `lib/` participates in the ingest + retrieval
pipeline. The mapping below ties each script to its role and
inputs.

| Script | Role | Inputs | Outputs / Side effects |
|---|---|---|---|
| `lib/seed.py` | **Ingest** — reads the controlled source-authority CSV and upserts one point per non-skipped row into `mpg_source_authority_documents`. | `--csv` (path to the source-authority CSV), `--collection`, `--url`, `--batch-size`, `--vector-dim`, `--embed auto\|on\|off`, `--marker-path` | Qdrant points in `mpg_source_authority_documents`; marker file at `$DATA_LAYER_QDRANT_INGEST_MARKER` (default `/opt/qdrant/state/last_ingest.json`) summarizing uploaded / skipped / batches / duration |
| `lib/embed.py` | **Encode** — lazy-loaded singleton wrapper around `sentence-transformers/all-mpnet-base-v2`. Exposes `Encoder.encode(text)` (single) and `Encoder.encode_batch(texts)` (batched). | `DATA_LAYER_QDRANT_EMBED_MODEL`, `DATA_LAYER_QDRANT_EMBED_BATCH_SIZE`, `HF_HOME` / `SENTENCE_TRANSFORMERS_HOME` | 768-float list per call; raises `RuntimeError` if the encoder produces a non-768 vector or if `sentence-transformers` is missing |
| `lib/mail_replay.py` | **Ingest (emails)** — reads an mbox file (RFC 4155) and dual-writes each message into `data-layer-postgres.emails` (INSERT, UNIQUE on `message_id`) then upserts into `mpg_emails` (HTTP PUT). | `--mbox`, `--postgres-dsn`, `--qdrant-url`, `--dry-run` | `data-layer-postgres.emails` rows + `mpg_emails` Qdrant points; `qdrant_ingested_y_n` flips to `'Y'` on success / `'N'` on qdrant failure |
| `lib/status.py` | **Observe** — prints Qdrant version + per-collection `points_count` / `status` / `vectors.size`. Used by `bootstrap status` and the smoke suite. | `--url` | human-readable status lines (no JSON, exit code 0/1) |
| `lib/qdrant.py` | **Operate** — Python subcommand helpers for one-shot ops: `apply-collection`, `apply-migrations`, `delete-collection`, `delete-all-collections`, `status`. Used by `qdrant.sh` and the bootstrap. | subcommand + `--url` + subcommand-specific flags | HTTP PUT/GET/DELETE against Qdrant; human-readable one-line output per op |
| `migrations/apply_migrations.py` | **Migrate** — walks `migrations/*.json` in sorted order; PUTs each into `PUT /collections/{name}` with idempotent skip-if-exists; re-GETs the live collection and diffs `config.params.vectors` against the spec (WARN on drift). | `DATA_LAYER_QDRANT_URL`, `DATA_LAYER_MIGRATIONS_DIR` | both collections created; WARN lines on drift; exit code 0 / 1 / 2 |

**Pipeline sequence (production):**

```
bash bootstrap install                      # docker compose / native binary up
  └─► docker-entrypoint.sh                  # first boot only
        ├─► apply_migrations.py             # both collections created (idempotent)
        └─► seed.sh                         # lib/seed.py against the source-authority CSV
bash bootstrap seed                         # re-seed (idempotent)
  └─► lib/seed.py                           # point id = md5(sha256); skip do_not_ingest_y_n='Y'
/opt/venv/bin/python lib/mail_replay.py ... # mbox replay -> postgres.emails + mpg_emails
bash bootstrap status                       # lib/status.py + rag.health smoke check
bash bootstrap verify                       # tests/smoke.sh
```

**Retrieval sequence (agent-driven):**

```
MCP (data-layer-adapters/mcp/server.py)
  └─► rag.search                            # rag.* tool, read-only by default
        ├─► POST /collections/mpg_source_authority_documents/points/search
        │     with always-on filter: do_not_ingest_y_n != 'Y' AND superseded_y_n != 'Y'
        └─► POST /collections/mpg_emails/points/search
              with upstream postgres filter on emails.qdrant_ingested_y_n = 'Y'
```

---

## Cross-links

- `../docs/SUBMODULE_OWNERSHIP.md` — umbrella ownership matrix;
  boundary rule #1 (no cross-submodule imports) + rule #4 (MCP
  exposes reads; writes through bootstrap) define what this project
  can and cannot do.
- `../data-layer-postgres/SCHEMAS.md` §13 — the `emails` table spec;
  the `qdrant_point_id` UNIQUE column is the reverse-link from
  postgres to `mpg_emails`.
- `../data-layer-adapters/TOOLS_AND_WIRING.md` — the 7 `rag.*` MCP
  tools (`rag.search`, `rag.collections.list`, `rag.collection.info`,
  `rag.health`, `rag.ingest.point`, `rag.ingest.batch`,
  `rag.ingest.status`); the two `rag.ingest.*` tools are the only
  writes and are gated by `MCP_INSTALL_MODE=1`.
- `docs/decisions/0001-rag-sot-architecture.md` — the ADR for the
  collection split, point-id scheme, idempotency rules, and gating
  policy referenced throughout this document.
- `lib/embed.py` — the encoder; the source of the 768-dim contract.
- `lib/seed.py` — the corpus seeder; the source of the
  `do_not_ingest_y_n` / `superseded_y_n` write-time rules.
- `lib/mail_replay.py` — the email ingestor; the source of the
  dual-write contract.
- `migrations/0001_collection_mpg_source_authority_documents.json`,
  `migrations/0002_collection_mpg_emails.json` — schema authority
  (see footer below).

---

## Schema-authority rule (footer)

> **Schema authority rule:** if this document disagrees with the
> migration `.json` file (`migrations/0001_collection_mpg_source_authority_documents.json`
> or `migrations/0002_collection_mpg_emails.json`), the migration
> wins. Update this document in the same commit that updates the
> schema. The same rule applies to `qdrant_config.yaml` for the
> service-level settings (host, port, storage paths) but NOT for
> per-collection payload fields — payload fields are owned by the
> migration JSON, not by the service config.
