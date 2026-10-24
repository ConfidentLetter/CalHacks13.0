"""Mock layout: regions and line boxes copied from mocks/page_twin_product_rule.json.

Used by ``segment`` until the classical segmenter is ready, and as the fallback
whenever the real segmenter raises (the demo must never go dark).
"""
from __future__ import annotations

import json
from functools import lru_cache

from layout._compat import REPO_ROOT

MOCK_TWIN_PATH = REPO_ROOT / "mocks" / "page_twin_product_rule.json"
MOCK_PAGE_SIZE = (1700, 2200)  # (width, height) of the mock dewarped page


@lru_cache(maxsize=1)
def load_mock_twin() -> dict:
    return json.loads(MOCK_TWIN_PATH.read_text())


def mock_regions() -> list[dict]:
    return [{"id": r["id"], "type": r["type"], "bbox": list(r["bbox"])} for r in load_mock_twin()["regions"]]


def mock_line_specs() -> list[dict]:
    """[{bbox, region_id, status_hint}] in reading order."""
    lines = sorted(load_mock_twin()["lines"], key=lambda l: l["order"])
    return [
        {
            "bbox": list(l["bbox"]),
            "region_id": l["region_id"],
            "status_hint": "crossed_out" if l["status"] == "crossed_out" else "active",
        }
        for l in lines
    ]
