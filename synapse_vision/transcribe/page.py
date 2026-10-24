"""transcribe_page: two independent readings per line, agreement, re-read, verbatim guard.

Step 1 version: returns mock-consistent lines so T4 can integrate. Real readings arrive in Step 3.
"""
from __future__ import annotations

from transcribe.compat import Timer
from transcribe.lines import strip_temporal
from transcribe.schema import load_mock_twin


def _mock_lines() -> list[dict]:
    return [strip_temporal(dict(line)) for line in load_mock_twin()["lines"]]


def transcribe_page(dewarped_path: str, layout: dict, previous_twin: dict | None = None) -> list[dict]:
    """Lines per page_twin.schema.json#/properties/lines (without first_seen/last_changed — build_page_twin sets those).
    Only re-transcribes lines whose crop changed since previous_twin (crop hash cache)."""
    with Timer("transcribe", mode="mock"):
        return _mock_lines()
