"""Optional cross-encoder rerank of the fused top candidates (ms-marco-MiniLM-L-6-v2, local CPU).

OFF by default (enable with BM_RERANK=1): measured on this laptop it costs ~1 s per query (budget 150 ms)
and ranked the BME280 "I2C address" query worse than BM25+vector fusion. Loads ONLY from the local Hugging
Face cache (never downloads at search time); fetch it with `python -m knowledge.tools.fetch_models`.
"""
from __future__ import annotations

import os
import threading

RERANK_MODEL = os.environ.get("BM_RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
ENABLED = os.environ.get("BM_RERANK", "0") == "1"
TOP_N = 10
_lock = threading.Lock()
_model = None
_failed = False


def get_model():
    global _model, _failed
    if _model is not None or _failed or not ENABLED:
        return _model
    with _lock:
        if _model is not None or _failed:
            return _model
        try:
            from sentence_transformers import CrossEncoder
            _model = CrossEncoder(RERANK_MODEL, device="cpu", local_files_only=True)
        except Exception:
            _failed = True
    return _model


def rerank(query: str, candidates: list[tuple[int, str]]) -> list[int] | None:
    """candidates = [(doc_index, text)] in fused order. Reranked doc indexes, or None (keep fused order)."""
    model = get_model()
    if model is None or not candidates:
        return None
    top = candidates[:TOP_N]
    try:
        scores = model.predict([(query, text) for _, text in top], show_progress_bar=False)
    except Exception:
        return None
    order = sorted(range(len(top)), key=lambda i: -float(scores[i]))
    return [top[i][0] for i in order] + [doc for doc, _ in candidates[TOP_N:]]
