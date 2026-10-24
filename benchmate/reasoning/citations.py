"""Datasheet citations and reading history via T4's knowledge module. Never raises."""
from __future__ import annotations

import re
import time
from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError as FutureTimeout
from typing import Any

from reasoning._telemetry import log as tlog
from reasoning.config import MAX_QUOTE_CHARS, SEARCH_BUDGET_MS, SEARCH_K_CITATION

_POOL = ThreadPoolExecutor(max_workers=2, thread_name_prefix="bm-search")

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _knowledge():
    try:
        import knowledge  # type: ignore
        return knowledge
    except Exception:
        return None


def _raw_search(part_id: str, query: str, k: int) -> list[dict[str, Any]]:
    kn = _knowledge()
    if kn is None:
        return []
    try:
        hits = kn.search(part_id, query, k=k) or []
    except Exception:
        return []
    return [h for h in hits if isinstance(h, dict)]


def safe_search(part_id: str | None, query: str | None, k: int = SEARCH_K_CITATION,
                budget_ms: float | None = None) -> list[dict[str, Any]]:
    """knowledge.search that never raises. With `budget_ms`, give up (return []) after that long;
    the search keeps running in a worker thread so T4's index is warm for the next call."""
    if not part_id or not query:
        return []
    if budget_ms is None:
        return _raw_search(part_id, query, k)
    fut: Future = _POOL.submit(_raw_search, part_id, query, k)
    try:
        return fut.result(timeout=budget_ms / 1000.0)
    except FutureTimeout:
        tlog("search_timeout", budget_ms, part_id=part_id, query=query[:60])
        return []
    except Exception:
        return []


def page_to_int(page: Any) -> int | None:
    """T4 returns page LABELS as strings ('22'); the diagnosis schema wants an integer."""
    if page is None:
        return None
    if isinstance(page, int):
        return page
    m = re.search(r"\d+", str(page))
    return int(m.group()) if m else None


def trim_quote(text: str, key_terms: list[str] | None, limit: int = MAX_QUOTE_CHARS) -> str:
    """The sentence containing the first key term found (e.g. '3.6'), cut to `limit` chars."""
    text = " ".join((text or "").split())
    if not text:
        return ""
    sentences = _SENTENCE_SPLIT.split(text)
    chosen = next((s for term in (key_terms or []) if term for s in sentences if term.lower() in s.lower()), None)
    if chosen is None:
        chosen = next((s for term in (key_terms or []) if term for s in [text] if term.lower() in s.lower()), sentences[0])
    if len(chosen) <= limit:
        return chosen
    for term in key_terms or []:
        pos = chosen.lower().find(term.lower()) if term else -1
        if pos >= 0:
            start = max(0, pos - limit // 2)
            return chosen[start:start + limit].strip()
    return chosen[:limit].strip()


def citation_for(part_id: str | None, query: str | None, key_terms: list[str] | None,
                 budget_ms: float | None = SEARCH_BUDGET_MS) -> dict[str, Any] | None:
    hits = [h for h in safe_search(part_id, query, budget_ms=budget_ms) if page_to_int(h.get("page")) is not None]
    if not hits:
        return None
    terms = [t.lower() for t in (key_terms or []) if t]
    best = next((h for t in terms for h in hits if t in (h.get("text") or "").lower()), hits[0])  # term priority first
    cite: dict[str, Any] = {"part_id": str(part_id), "page": page_to_int(best.get("page"))}
    quote = trim_quote(best.get("text", ""), key_terms)
    if quote:
        cite["quote"] = quote
    return cite


def was_read(part_id: str | None, page: int | None) -> bool:
    kn = _knowledge()
    if kn is None or not part_id or page is None:
        return False
    try:
        reads = kn.recent_reads(part_id) or []
    except Exception:
        return False
    return any(page_to_int(r.get("page")) == page for r in reads if isinstance(r, dict))


def cite_finding(finding: dict[str, Any], deadline: float | None = None) -> dict[str, Any]:
    """Return a copy of `finding` with a datasheet citation (and read-history note) when available.
    `deadline` is a time.perf_counter() value shared by all findings of one diagnosis; None = no limit."""
    meta = finding.get("_meta", {})
    budget = None if deadline is None else max(0.0, (deadline - time.perf_counter()) * 1000)
    if budget is not None and budget < 5:
        return finding
    cite = citation_for(meta.get("part_id"), meta.get("search_query"), meta.get("key_terms"), budget_ms=budget)
    if cite is None:
        return finding
    explanation = finding["explanation"]
    if was_read(cite["part_id"], cite["page"]):
        explanation = explanation.rstrip() + " You read this page earlier today."
    return {**finding, "explanation": explanation,
            "evidence": {**finding["evidence"], "datasheet": [cite]}}
