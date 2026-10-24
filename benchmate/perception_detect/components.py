"""detect_components: Tier A registrations + Tier B OWLv2 detections, A always wins."""
from __future__ import annotations

import copy
import json
import os
from typing import Any

from ._telemetry import log, timed
from .config import tier_b_enabled
from .geometry_bridge import calibrate
from .paths import MOCK_TWIN_OK_PATH
from .registration import set_current_homography
from .tier_a import tier_a_components

_last_needs_register: list[dict] = []


def mock_components() -> list[dict]:
    return copy.deepcopy(json.loads(MOCK_TWIN_OK_PATH.read_text())["components"])


def mock_mode() -> bool:
    return os.environ.get("BM_MOCK", "").strip() not in ("", "0", "false", "False")


def last_needs_register() -> list[dict]:
    """Register prompts from the most recent detect_components (shape of diagnosis.needs_user_confirmation)."""
    return list(_last_needs_register)


def _frame_size(frame_path: str) -> tuple[int, int] | None:
    try:
        import cv2

        img = cv2.imread(str(frame_path))
        return None if img is None else (img.shape[1], img.shape[0])
    except Exception:
        return None


def _run_tier_b(frame_path: str, tiles: list[dict] | None, homography: Any, info: dict,
                calibrated: bool = True) -> list[dict]:
    """OWLv2 detections; skipped (not failed) when disabled or when the weights are not on disk."""
    global _last_needs_register
    _last_needs_register = []
    if not tier_b_enabled():
        info["tier_b"] = "disabled"
        return []
    from . import owl
    from .tier_b import tier_b_components

    if not owl.weights_cached():
        info["tier_b"] = "weights not cached (python -m perception_detect.owl --download)"
        return []
    try:
        comps, needs = tier_b_components(frame_path, tiles, homography, detector=owl.detect,
                                         frame_size=_frame_size(frame_path), calibrated=calibrated)
    except Exception as exc:
        info["tier_b"] = f"error {type(exc).__name__}: {exc}"[:160]
        log("tier_b.error", 0.0, error=info["tier_b"])
        return []
    _last_needs_register = needs
    info["tier_b"] = len(comps)
    return comps


def detect_components(frame_path: str, tiles: list[dict] | None = None,
                      *, homography: Any | None = None, calibrated: bool = True) -> list[dict]:
    """Components per twin.schema.json, part_id normalized, pins mapped to holes.

    Tier A (registered clicks) always overrides Tier B for the same part_id. `homography` is an
    optional extra kwarg so build_twin can pass the calibration it already computed.
    BM_MOCK=1 returns the mock components; BM_TIER_B=0 skips OWLv2.
    """
    from .tier_b import merge_tiers

    with timed("detect_components", frame=str(frame_path), tiles=len(tiles or [])) as info:
        if mock_mode():
            info["mock"] = True
            return mock_components()
        if homography is None:
            cal = calibrate(frame_path)
            homography, calibrated = cal.homography, cal.calibrated
            if cal.error:
                info["calibrate_error"] = cal.error
            set_current_homography(homography, calibrated=calibrated)
        info["calibrated"] = calibrated
        tier_a = tier_a_components(homography, calibrated=calibrated)
        info["tier_a"] = len(tier_a)
        tier_b = _run_tier_b(frame_path, tiles, homography, info, calibrated=calibrated)
        return merge_tiers(tier_a, tier_b)
