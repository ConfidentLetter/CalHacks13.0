"""Local sentence embeddings (all-MiniLM-L6-v2). Loaded once, lazily, ONLY from the local Hugging Face cache.

Nothing here touches the network at request time: `python -m knowledge.tools.fetch_models` downloads the
weights once. If the model is not cached, encode() returns None and search runs BM25-only.
"""
from __future__ import annotations

import os
import threading

import numpy as np

MODEL_NAME = os.environ.get("BM_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
EMBED_DIM = 384
_lock = threading.Lock()
_model = None
_failed = False


def get_model():
    global _model, _failed
    if _model is not None or _failed:
        return _model
    with _lock:
        if _model is not None or _failed:
            return _model
        try:
            from sentence_transformers import SentenceTransformer
            _model = SentenceTransformer(MODEL_NAME, device="cpu", local_files_only=True)
        except Exception:
            _failed = True
            _model = None
    return _model


def encode(texts: list[str]) -> np.ndarray | None:
    """Unit-normalised float32 embeddings, shape (n, d). None if the model is unavailable."""
    if not texts:
        return np.zeros((0, EMBED_DIM), dtype=np.float32)
    model = get_model()
    if model is None:
        return None
    try:
        vecs = model.encode(texts, batch_size=64, convert_to_numpy=True, normalize_embeddings=True,
                            show_progress_bar=False)
    except Exception:
        return None
    return np.asarray(vecs, dtype=np.float32)


def available() -> bool:
    return get_model() is not None
