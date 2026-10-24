"""Hybrid datasheet search: BM25 (rank_bm25) + MiniLM vectors, merged with reciprocal rank fusion (k=60),
optional local cross-encoder rerank. Never raises, never touches the network: on any internal failure it
degrades (rerank -> vectors -> BM25 -> []) and logs the reason.

Hit shape (contracts/interfaces.md): {text, page, section, score, source_file}.
`page` is always the page LABEL a human sees in a PDF viewer, as a string.
`text` is a parent-page window (<= 1200 chars) around the matching chunk.
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass

import numpy as np

from . import embeddings as _emb
from . import rerank as _rerank
from ._telemetry import log, timed
from .paths import INDEX_DIR, MOCKS_DIR
from .textutil import parent_window, tokenize
from .validation import is_valid_part_id

RRF_K = 60
CANDIDATES = 20  # per retriever before fusion
_MOCK_FILE = MOCKS_DIR / "search_bme280_supply.json"


@dataclass
class _Index:
    chunks: list[dict]
    pages: dict[str, dict[str, str]]
    bm25: object
    emb: np.ndarray | None
    key: tuple


_cache: dict[str, _Index] = {}
_cache_lock = threading.Lock()
_load_locks: dict[str, threading.Lock] = {}


def invalidate(part_id: str | None = None) -> None:
    with _cache_lock:
        if part_id is None:
            _cache.clear()
        else:
            _cache.pop(part_id, None)


def _index_key(part_id: str) -> tuple | None:
    """Identity of the on-disk index: (mtime_ns, size) of all three files. None if there is no index."""
    from .ingestion import index_paths
    parts = []
    for p in index_paths(part_id):
        try:
            st = p.stat()
            parts.append((st.st_mtime_ns, st.st_size))
        except FileNotFoundError:
            parts.append(None)
    return tuple(parts) if parts[0] is not None else None


def _load_lock(part_id: str) -> threading.Lock:
    with _cache_lock:
        return _load_locks.setdefault(part_id, threading.Lock())


def _build(part_id: str, key: tuple) -> _Index | None:
    from rank_bm25 import BM25Okapi
    from .ingestion import load_chunks, load_embeddings, load_pages

    chunks = load_chunks(part_id)
    if not chunks:
        return None
    tokens = [tokenize(c["text"]) for c in chunks]
    if not any(tokens):
        return None
    bm25 = BM25Okapi(tokens)
    emb = load_embeddings(part_id)
    if emb is not None and (len(emb) != len(chunks) or emb.shape[1] != _emb.EMBED_DIM):
        emb = None
    return _Index(chunks=chunks, pages=load_pages(part_id), bm25=bm25, emb=emb, key=key)


def _load(part_id: str) -> _Index | None:
    key = _index_key(part_id)
    if key is None:
        return None
    with _cache_lock:
        cached = _cache.get(part_id)
    if cached is not None and cached.key == key:
        return cached
    with _load_lock(part_id):  # single-flight: one thread builds, the others wait and reuse
        with _cache_lock:
            cached = _cache.get(part_id)
        if cached is not None and cached.key == key:
            return cached
        idx = _build(part_id, key)
        if idx is not None:
            with _cache_lock:
                _cache[part_id] = idx
        return idx


def warmup(part_ids: list[str] | None = None) -> None:
    """Load the embedding + rerank models and the indexes once (T5 calls this at server start)."""
    _emb.get_model()
    _rerank.get_model()
    ids = part_ids if part_ids is not None else sorted(p.stem for p in INDEX_DIR.glob("*.jsonl"))
    for pid in ids:
        if is_valid_part_id(pid):
            try:
                _load(pid)
            except Exception as exc:
                log("knowledge.warmup_failed", 0.0, part_id=pid, error=str(exc)[:160])


def _rank_bm25(idx: _Index, query: str) -> list[int]:
    scores = np.asarray(idx.bm25.get_scores(tokenize(query)))
    order = np.argsort(-scores, kind="stable")
    return [int(i) for i in order[:CANDIDATES] if scores[i] > 0]


def _rank_vector(idx: _Index, query: str) -> list[int]:
    if idx.emb is None:
        return []
    q = _emb.encode([query])
    if q is None or q.shape[1] != idx.emb.shape[1]:
        return []
    sims = idx.emb @ q[0]
    order = np.argsort(-sims, kind="stable")
    return [int(i) for i in order[:CANDIDATES]]


def _rrf(rankings: list[list[int]], k: int = RRF_K) -> dict[int, float]:
    fused: dict[int, float] = {}
    for ranking in rankings:
        for rank, doc in enumerate(ranking):
            fused[doc] = fused.get(doc, 0.0) + 1.0 / (k + rank + 1)
    return fused


def _to_hit(idx: _Index, chunk: dict, score: float) -> dict:
    page_text = idx.pages.get(chunk["source_file"], {}).get(chunk["page"], chunk["text"])
    return {
        "text": parent_window(page_text, chunk["text"]),
        "page": str(chunk["page"]),
        "section": chunk.get("section", "") or "",
        "score": round(float(score), 6),
        "source_file": chunk["source_file"],
    }


def _mock_hits() -> list[dict]:
    try:
        with _MOCK_FILE.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
    except Exception:
        return []
    return [{"text": (h.get("text") or "")[:1200], "page": str(h.get("page")), "section": h.get("section") or "",
             "score": float(h.get("score") or 0.0), "source_file": h.get("source_file") or ""} for h in raw]


def _ordered_docs(idx: _Index, query: str) -> list[tuple[int, float]]:
    """Candidate chunk indexes with scores, best first. Each stage degrades independently."""
    bm25 = _rank_bm25(idx, query)
    try:
        vec = _rank_vector(idx, query)
    except Exception as exc:
        log("knowledge.search_degraded", 0.0, step="vector", error=str(exc)[:160])
        vec = []
    fused = _rrf([bm25, vec])
    ordered = [doc for doc, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
    try:
        reranked = _rerank.rerank(query, [(doc, idx.chunks[doc]["text"]) for doc in ordered])
    except Exception as exc:
        log("knowledge.search_degraded", 0.0, step="rerank", error=str(exc)[:160])
        reranked = None
    if reranked is None:
        return [(doc, fused[doc]) for doc in ordered]
    return [(doc, 1.0 / (RRF_K + rank + 1)) for rank, doc in enumerate(reranked)]


def search(part_id: str, query: str, k: int = 5) -> list[dict]:
    """Hybrid keyword+vector search. Each hit: {text, page, section, score, source_file}.
    `page` is the page label a human sees in a PDF viewer. `text` is the parent-page window, <= 1200 chars."""
    if not is_valid_part_id(part_id) or not isinstance(query, str) or not query.strip():
        return []
    try:
        k = int(k)
    except (TypeError, ValueError):
        return []
    if k <= 0:
        return []
    try:
        with timed("search", part_id=part_id, k=k):
            idx = _load(part_id)
            if idx is None:
                # Demo backup only (BM_MOCK=1, T5's mock mode): the day-one mock hit for bme280.
                if part_id == "bme280" and os.environ.get("BM_MOCK") == "1":
                    return _mock_hits()[:k]
                log("knowledge.search_no_index", 0.0, part_id=part_id)
                return []
            hits: list[dict] = []
            seen_pages: set[tuple[str, str]] = set()
            for doc, score in _ordered_docs(idx, query):
                chunk = idx.chunks[doc]
                key = (chunk["source_file"], str(chunk["page"]))
                if key in seen_pages:
                    continue  # one hit per page: the parent window already covers sibling chunks
                seen_pages.add(key)
                hits.append(_to_hit(idx, chunk, score))
                if len(hits) >= k:
                    break
            return hits
    except Exception as exc:  # never let a search failure become a server 500
        log("knowledge.search_failed", 0.0, part_id=part_id, error=f"{type(exc).__name__}: {exc}"[:200])
        return []
