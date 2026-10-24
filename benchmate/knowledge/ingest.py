"""Datasheet ingestion. Step 1 stub: validates inputs and returns 0 chunks. Real pipeline in Step 3."""
from __future__ import annotations

from pathlib import Path

from ._telemetry import timed


def ingest(pdf_path: str, part_id: str) -> int:
    """Extract, chunk, index a datasheet. Returns number of chunks. Idempotent."""
    path = Path(pdf_path)
    if not path.is_file():
        raise FileNotFoundError(pdf_path)
    if not part_id:
        raise ValueError("part_id is required")
    with timed("ingest", part_id=part_id, stub=True):
        return 0
