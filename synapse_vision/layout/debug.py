"""Debug overlay: every line box with its order number, crossed-out lines hatched."""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from layout._compat import REPO_ROOT

COLORS = {"active": (0, 170, 0), "crossed_out": (0, 0, 230), "unsure": (0, 150, 255)}
REGION_COLOR = (200, 120, 0)
HATCH_STEP = 14


def debug_dir() -> Path:
    d = REPO_ROOT / "runtime" / "debug"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hatch(img: np.ndarray, x: int, y: int, w: int, h: int, color: tuple[int, int, int]) -> None:
    for off in range(-h, w, HATCH_STEP):
        p0 = (max(x, x + off), y + (max(0, -off)))
        p1 = (min(x + w, x + off + h), y + h - max(0, off + h - w))
        if p1[0] > p0[0]:
            cv2.line(img, p0, p1, color, 1, cv2.LINE_AA)


def write_debug_overlay(img: np.ndarray, layout_result: dict, snapshot_id: str) -> Path:
    canvas = img.copy() if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    for r in layout_result["regions"]:
        x, y, w, h = (int(v) for v in r["bbox"])
        cv2.rectangle(canvas, (x - 6, y - 6), (x + w + 6, y + h + 6), REGION_COLOR, 1)
        cv2.putText(canvas, f'{r["id"]}:{r["type"]}', (x - 6, max(14, y - 10)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, REGION_COLOR, 1)
    for line in layout_result["lines"]:
        x, y, w, h = (int(v) for v in line["bbox"])
        color = COLORS.get(line["status_hint"], COLORS["unsure"])
        cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 2)
        if line["status_hint"] == "crossed_out":
            _hatch(canvas, x, y, w, h, color)
        cv2.putText(canvas, str(line.get("order", "?")), (max(2, x - 40), y + min(h, 28)), cv2.FONT_HERSHEY_SIMPLEX, 0.9, (255, 0, 0), 2)
    out = debug_dir() / f"layout_{snapshot_id}.png"
    cv2.imwrite(str(out), canvas)
    return out
