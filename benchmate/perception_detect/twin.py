"""build_twin: assemble the circuit twin (Step 1: mock-backed; Step 5 wires in T1)."""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from ._telemetry import timed
from .paths import MOCK_TWIN_OK_PATH
from .schema import assert_valid_twin


def _frame_id(frame_path: str) -> str:
    """Stable id for a frame: sha1 of file bytes if it exists, else of the path string."""
    p = Path(frame_path)
    h = hashlib.sha1()
    if p.is_file():
        h.update(p.read_bytes())
    else:
        h.update(str(frame_path).encode("utf-8"))
    return "f_" + h.hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def mock_twin(frame_path: str) -> dict:
    """Content of mocks/twin_ok.json with a fresh frame_id and timestamp."""
    base = json.loads(MOCK_TWIN_OK_PATH.read_text())
    twin = copy.deepcopy(base)
    return {**twin, "frame_id": _frame_id(frame_path), "timestamp": _now_iso()}


def build_twin(frame_path: str) -> dict:
    """calibrate -> tile -> components -> wires (excluding component boxes) -> nets.

    Step 1: returns the mock twin with a fresh frame_id/timestamp so T3/T5 can integrate.
    """
    with timed("build_twin", frame=str(frame_path)):
        twin = mock_twin(frame_path)
    assert_valid_twin(twin)
    return twin
