#!/usr/bin/env python3
"""data-layer-qdrant/lib/mail_replay.py — minimal mbox replay.

Reads a Unix mbox file (RFC 4155) and for each message:
  1. INSERTs into postgres.emails (table from 0007_emails.sql)
     with columns mapped from RFC 5322 headers:
       Message-ID      -> message_id  (UNIQUE; idempotency key)
       From            -> from_email
       To              -> to_emails (JSONB list)
       Cc              -> cc_emails (JSONB list)
       Subject         -> subject
       Date            -> received_at (parsed via email.utils.parsedate_to_datetime)
       payload         -> body (text/plain or text/html)
  2. Upserts the same row into qdrant.mpg_emails via the MCP
     rag.ingest.point endpoint with MCP_INSTALL_MODE=1 (gated
     write — see data-layer-adapters/mcp/tools/rag.py::rag.ingest.point
     for the gate semantics).
  3. Updates postgres.emails.qdrant_ingested_y_n = 'Y' once the
     qdrant upsert returns ok; 'SUPERSEDED' if the qdrant point
     was an updated version of an existing row (idempotent re-run);
     'DO_NOT_INGEST' (no-op) if the message body is empty or
     headers are missing critical fields.

Why an mbox replay instead of a live SMTP listener:
  * Smallest useful end-to-end implementation
  * Deterministic — you can replay any historical .mbox to seed
  * No need to expose SMTP ports
  * Tests can ship a fixture mbox and run replays end-to-end

Live SMTP listener extension (production path):
  * Stub a smtpd.DebuggingServer (stdlib) or aiosmtpd
  * Same ingest path: INSERT into emails, rag.ingest.point,
    UPDATE qdrant_ingested_y_n.
  * Gate via MCP_INSTALL_MODE (same as the replay).

Wire-up:
    set -a; source /a0/usr/projects/data-layer/.env; set +a
    DATA_LAYER_INSTALL_MODE=1 MCP_INSTALL_MODE=1 \n        /opt/venv/bin/python lib/mail_replay.py \n            --mbox /var/mail/legacy.mbox \n            --postgres-dsn "$DATA_LAYER_POSTGRES_DSN" \n            --qdrant-url "$DATA_LAYER_QDRANT_URL" \n            --project-id 00000000-0000-0000-0000-000000000000
"""
from __future__ import annotations

import argparse
import email
import email.policy
import json
import os
import sys
import urllib.error
import urllib.request
from email.utils import getaddresses, parsedate_to_datetime
from typing import Any, Dict, List, Optional


def _qdrant_put(url: str, body: Dict[str, Any], timeout: int = 30) -> Dict[str, Any]:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method="PUT",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())
