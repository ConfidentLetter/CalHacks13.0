"""Line-record construction helpers shared by the mock and real paths."""
from __future__ import annotations

from typing import Any

LINE_OUTPUT_KEYS = ("id", "region_id", "order", "bbox", "status", "kind", "latex", "text",
                    "confidence", "uncertain_spans", "parse_ok")


def strip_temporal(line: dict) -> dict:
    """Lines returned by transcribe_page carry no first_seen/last_changed (build_page_twin sets them)."""
    return {k: v for k, v in line.items() if k not in ("first_seen", "last_changed")}


def make_line(*, region_id: str, order: int, bbox: list, status: str, kind: str, latex: str, text: str,
              confidence: float, uncertain_spans: list[dict] | None = None, parse_ok: bool = False,
              extra: dict[str, Any] | None = None) -> dict:
    line = {
        "id": "",
        "region_id": region_id,
        "order": int(order),
        "bbox": [float(v) for v in bbox],
        "status": status,
        "kind": kind,
        "latex": latex,
        "text": text,
        "confidence": max(0.0, min(1.0, float(confidence))),
        "uncertain_spans": list(uncertain_spans or []),
        "parse_ok": bool(parse_ok),
    }
    if extra:
        line.update(extra)
    return line


def illegible_line(*, region_id: str, order: int, bbox: list, reason: str = "") -> dict:
    return make_line(region_id=region_id, order=order, bbox=bbox, status="illegible", kind="text",
                     latex="", text="", confidence=0.0, parse_ok=False,
                     extra={"_debug": {"reason": reason}} if reason else None)
