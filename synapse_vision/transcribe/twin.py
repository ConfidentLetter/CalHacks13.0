"""build_page_twin: the full pipeline, assembled into a schema-valid page twin.

Step 1 version: returns the mock twin with a fresh snapshot_id / captured_at, validated.
"""
from __future__ import annotations

from transcribe.compat import Timer
from transcribe.ids import new_snapshot_id, now_iso
from transcribe.schema import load_mock_twin, validate_twin


def mock_twin(snapshot_path: str = "", source: str = "mock") -> dict:
    """The committed mock twin, re-stamped. Used as the Step-1 stub and as the demo backup (SV_MOCK=1)."""
    twin = load_mock_twin()
    image = {**twin["image"], "original_path": snapshot_path or twin["image"]["original_path"]}
    return validate_twin({**twin, "snapshot_id": new_snapshot_id(), "captured_at": now_iso(),
                          "source": source, "image": image})


def build_page_twin(snapshot_path: str, previous_twin: dict | None = None) -> dict:
    """Full pipeline: T1 detect_and_dewarp -> T2 segment -> transcribe_page -> match lines to previous_twin
    (stable ids, changes.added/edited/removed/crossed_out, first_seen/last_changed) -> validate against page_twin.schema.json."""
    with Timer("build_page_twin", mode="mock"):
        return mock_twin(snapshot_path)
