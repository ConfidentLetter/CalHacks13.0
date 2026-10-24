"""Hybrid datasheet search: BM25 (rank_bm25) + MiniLM vectors, merged with reciprocal rank fusion (k=60).

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
from ._telemetry import timed
from .paths import INDEX_DIR, MOCKS_DIR
from .textutil import parent_window, tokenize

RRF_K = 60
CANDIDATES = 20  # per retriever before fusion
_MOCK_FILE = MOCKS_DIR / "search_bme280_supply.json"
_HIT_KEYS = ("text", "page", "section", "score", "source_file")


@dataclass
class _Index:
    chunks: list[dict]
    pages: dict[str, dict[str, str]]
    bm25: object
    emb: np.ndarray | None
    mtime: float


_cache: dict[str, _Index] = {}
_cache_lock = threading.Lock()


def invalidate(part_id: str | None = None) -> None:
    with _cache_lock:
        if part_id is None:
            _cache.clear()
        else:
            _cache.pop(part_id, None)


def _index_mtime(part_id: str) -> float:
    f = INDEX_DIR / f"{part_id}.jsonl"
    return f.stat().st_mtime if f.is_file() else -1.0


def _load(part_id: str) -> _Index | None:
    from rank_bm25 import BM25Okapi
    from .ingestion import load_chunks, load_embeddings, load_pages

    mtime = _index_mtime(part_id)
    if mtime < 0:
        return None
    with _cache_lock:
        cached = _cache.get(part_id)
        if cached is not None and cached.mtime == mtime:
            return cached
    chunks = load_chunks(part_id)
    if not chunks:
        return None
    bm25 = BM25Okapi([tokenize(c["text"]) for c in chunks])
    emb = load_embeddings(part_id)
    if emb is not None and len(emb) != len(chunks):
        emb = None
    idx = _Index(chunks=chunks, pages=load_pages(part_id), bm25=bm25, emb=emb, mtime=mtime)
    with _cache_lock:
        _cache[part_id] = idx
    return idx


def warmup(part_ids: list[str] | None = None) -> None:
    """Load the embedding + rerank models and the indexes once (T5 may call this at server start)."""
    _emb.get_model()
    _rerank.get_model()
    ids = part_ids if part_ids is not None else [p.stem for p in INDEX_DIR.glob("*.jsonl")]
    for pid in ids:
        _load(pid)


def _rank_bm25(idx: _Index, query: str) -> list[int]:
    scores = np.asarray(idx.bm25.get_scores(tokenize(query)))
    order = np.argsort(-scores, kind="stable")
    return [int(i) for i in order[:CANDIDATES] if scores[i] > 0]


def _rank_vector(idx: _Index, query: str) -> list[int]:
    if idx.emb is None:
        return []
    q = _emb.encode([query])
    if q is None:
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
    with _MOCK_FILE.open("r", encoding="utf-8") as fh:
        raw = json.load(fh)
    return [{"text": (h.get("text") or "")[:1200], "page": str(h.get("page")), "section": h.get("section") or "",
             "score": float(h.get("score") or 0.0), "source_file": h.get("source_file") or ""} for h in raw]


def search(part_id: str, query: str, k: int = 5) -> list[dict]:
    """Hybrid keyword+vector search. Each hit: {text, page, section, score, source_file}.
    `page` is the page label a human sees in a PDF viewer. `text` is the parent-page window, <= 1200 chars."""
    if not part_id or not query or int(k) <= 0:
        return []
    k = int(k)
    with timed("search", part_id=part_id, k=k):
        idx = _load(part_id)
        if idx is None:
            # No index yet for this part: keep T3 unblocked with the day-one mock for bme280 only.
            return _mock_hits()[:k] if part_id == "bme280" else []
        fused = _rrf([_rank_bm25(idx, query), _rank_vector(idx, query)])
        ordered = [doc for doc, _ in sorted(fused.items(), key=lambda kv: -kv[1])]
        reranked = _rerank.rerank(query, [(doc, idx.chunks[doc]["text"]) for doc in ordered])
        if reranked is not None:
            ordered = reranked
        hits: list[dict] = []
        seen_pages: set[tuple[str, str]] = set()
        for rank, doc in enumerate(ordered):
            score = fused.get(doc, 0.0) if reranked is None else 1.0 / (RRF_K + rank + 1)
            chunk = idx.chunks[doc]
            key = (chunk["source_file"], str(chunk["page"]))
            if key in seen_pages:
                continue  # one hit per page: the parent window already covers sibling chunks
            seen_pages.add(key)
            hits.append(_to_hit(idx, chunk, score))
            if len(hits) >= k:
                break
        return hits


if os.environ.get("BM_KNOWLEDGE_EAGER") == "1":  # pragma: no cover
    threading.Thread(target=warmup, daemon=True).start()
