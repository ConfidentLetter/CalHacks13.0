"""Tunable knobs for Tier B. Tune on eval/testset and record each change as an eval row note."""
from __future__ import annotations

import os

OWL_MODEL_ID = "google/owlv2-base-patch16-ensemble"
OWL_QUERIES: tuple[str, ...] = (
    "a microcontroller development board",
    "a small electronic sensor breakout board",
    "a breadboard",
)
# Queries whose boxes are the board itself, not a component. Asking for it gives the model a
# competing class for board-sized regions; its boxes are discarded before NMS.
OWL_IGNORE_QUERIES: frozenset[str] = frozenset({"a breadboard"})
OWL_SCORE_THRESHOLD = 0.2
NMS_IOU = 0.5
TIER_B_CONFIDENCE_CAP = 0.95
MAX_COMPONENT_BOARD_FRACTION = 0.6   # a box covering more of the frame than this is not a component


def tier_b_enabled() -> bool:
    """BM_TIER_B=0 disables OWLv2; default on (it still skips itself if the weights are not cached)."""
    return os.environ.get("BM_TIER_B", "1").strip() not in ("0", "false", "False")
