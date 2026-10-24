"""Hybrid datasheet search. Step 1: returns the mock hit list from mocks/search_bme280_supply.json.

Hit shape (contracts/interfaces.md): {text, page, section, score, source_file}.
`page` is always the page LABEL a human sees in a PDF viewer, returned as a string.
"""
from __future__ import annotations

import json

from ._telemetry import timed
from .paths import MOCKS_DIR

_MOCK_FILE = MOCKS_DIR / "search_bme280_supply.json"
_HIT_KEYS = ("text", "page", "section", "score", "source_file")


def _normalize_hit(hit: dict) -> dict:
    out = {k: hit.get(k) for k in _HIT_KEYS}
    out["page"] = str(out["page"]) if out["page"] is not None else None
    out["text"] = (out["text"] or "")[:1200]
    out["score"] = float(out["score"] or 0.0)
    return out


def _mock_hits() -> list[dict]:
    with _MOCK_FILE.open("r", encoding="utf-8") as fh:
        return [_normalize_hit(h) for h in json.load(fh)]


def search(part_id: str, query: str, k: int = 5) -> list[dict]:
    """Hybrid keyword+vector search. Each hit: {text, page, section, score, source_file}.
    `page` is the page label a human sees in a PDF viewer. `text` is the parent-page window, <= 1200 chars."""
    if not part_id or not query:
        return []
    with timed("search", part_id=part_id, k=k, mock=True):
        return _mock_hits()[: max(0, int(k))]
