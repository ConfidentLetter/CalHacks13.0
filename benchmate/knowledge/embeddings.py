"""Local sentence embeddings (all-MiniLM-L6-v2). Loaded once, lazily; never calls a paid API.

If the model cannot be loaded (offline, package missing) encode() returns None and search runs BM25-only.
"""
from __future__ import annotations

import os
import threading

import numpy as np

MODEL_NAME = os.environ.get("BM_EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
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
            _model = _load_offline_first(SentenceTransformer, MODEL_NAME)
        except Exception:
            _failed = True
            _model = None
    return _model


def _load_offline_first(cls, name: str):
    """Cached weights load in ~0.1 s; the online hub check can stall for minutes on a flaky network."""
    try:
        return cls(name, device="cpu", local_files_only=True)
    except Exception:
        return cls(name, device="cpu")


def encode(texts: list[str]) -> np.ndarray | None:
    """Unit-normalised float32 embeddings, shape (n, d). None if the model is unavailable."""
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    model = get_model()
    if model is None:
        return None
    vecs = model.encode(texts, batch_size=64, convert_to_numpy=True, normalize_embeddings=True,
                        show_progress_bar=False)
    return np.asarray(vecs, dtype=np.float32)


def available() -> bool:
    return get_model() is not None
