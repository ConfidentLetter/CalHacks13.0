"""Reading history: knowledge/reads.jsonl. Step 1 stub: record_read is a no-op, recent_reads returns []."""
from __future__ import annotations

from ._telemetry import timed


def record_read(url_or_path: str, text: str | None, seconds_on_page: float) -> None:
    """Log that the user read something (called via POST /read from the browser extension)."""
    with timed("record_read", stub=True):
        return None


def recent_reads(part_id: str | None = None, hours: int = 24) -> list[dict]:
    """[{part_id, page, title, read_at, seconds}] newest first."""
    return []
