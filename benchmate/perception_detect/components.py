"""detect_components: Tier A registrations + Tier B detections (Step 1: mock components)."""
from __future__ import annotations

import copy
import json

from ._telemetry import timed
from .paths import MOCK_TWIN_OK_PATH


def mock_components() -> list[dict]:
    return copy.deepcopy(json.loads(MOCK_TWIN_OK_PATH.read_text())["components"])


def detect_components(frame_path: str, tiles: list[dict] | None = None) -> list[dict]:
    """Components per twin.schema.json, part_id normalized, pins mapped to holes.

    Step 1: returns the components of mocks/twin_ok.json.
    """
    with timed("detect_components", frame=str(frame_path), tiles=len(tiles or [])):
        return mock_components()
