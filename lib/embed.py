#!/usr/bin/env python3
"""data-layer-qdrant/lib/embed.py — sentence-transformers wrapper.

Lazy-loads the all-mpnet-base-v2 model on first call and exposes
encode(text) -> list[float] returning a 768-dim vector compatible
with the qdrant collections configured for vectors.size=768
distance=Cosine.

Per the HANDOFF §10 gap-list: today seed.py uploads placeholder
zero-vectors. This module is the scaffold that, when wired into
seed.py, replaces those zero-vectors with real embeddings.

Per-project env conventions:
  * HF_HOME / SENTENCE_TRANSFORMERS_HOME — model cache directory
  * DATA_LAYER_QDRANT_EMBED_MODEL — override the default model
  * DATA_LAYER_QDRANT_EMBED_BATCH_SIZE — sentence-encoder batch size

Usage:

    from embed import get_encoder
    enc = get_encoder()
    vec = enc.encode("qdrant cosine similarity")
    assert len(vec) == 768
"""
from __future__ import annotations

import os
import threading
from typing import Any, List, Optional

DEFAULT_MODEL = "sentence-transformers/all-mpnet-base-v2"
EXPECTED_DIM = 768

# Lazy-load sentinel so we don't pay the ~400MB model download cost
# until the first encode() call.
_encoder = None
_encoder_lock = threading.Lock()


def _model_name() -> str:
    return os.environ.get("DATA_LAYER_QDRANT_EMBED_MODEL", DEFAULT_MODEL)


def _batch_size() -> int:
    try:
        return int(os.environ.get("DATA_LAYER_QDRANT_EMBED_BATCH_SIZE", "32"))
    except ValueError:
        return 32


def get_encoder() -> "Encoder":
    """Lazy-loaded singleton. Thread-safe."""
    global _encoder
    if _encoder is None:
        with _encoder_lock:
            if _encoder is None:
                _encoder = Encoder()
    return _encoder


def warmup() -> dict:
    """Eagerly load the model. Returns a status dict suitable for
    rag.ingest.status / bootstrap status output.

    Use this from data-layer-qdrant/bootstrap install to pre-download
    the model into the local HF cache (saves ~400MB once).
    """
    enc = get_encoder()
    # One warm-up encode to confirm the model is functional.
    _ = enc.encode("warmup")
    return {
        "model": _model_name(),
        "dim": EXPECTED_DIM,
        "status": "ready",
    }


class Encoder:
    def __init__(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers is not installed; pip install "
                "sentence-transformers>=3.0,<4 to enable real "
                "embeddings. Until then seed.py falls back to [0.0] "
                "* 768 placeholders."
            ) from e
        self._model = SentenceTransformer(_model_name())

    def encode(self, text: str) -> List[float]:
        if not isinstance(text, str):
            text = str(text)
        vec = self._model.encode(
            [text],
            batch_size=1,
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        out = vec[0].tolist()
        if len(out) != EXPECTED_DIM:
            raise RuntimeError(
                "encoder produced " + str(len(out)) + "-dim vector; "
                "expected " + str(EXPECTED_DIM)
            )
        return out

    def encode_batch(self, texts: List[str]) -> List[List[float]]:
        if not texts:
            return []
        vecs = self._model.encode(
            list(texts),
            batch_size=_batch_size(),
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return [v.tolist() for v in vecs]
