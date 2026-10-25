"""Last-resort read when T1 finds no page and T2 returns no lines (paper held up, corners out of frame).

The raw still goes to the same page pass the normal pipeline uses (same verbatim prompt, same strict JSON).
Geometry is unknown here, so each line gets an estimated horizontal band as its box and carries
`bbox_estimated: true`; confidence is capped by the usual bad-quality rule (quality.ok stays False).
Nothing is corrected: the readings are the model's verbatim transcription, exactly as in the page pass.
"""
from __future__ import annotations

from transcribe.compare import model_spans
from transcribe.compat import Timer
from transcribe.lines import make_line
from transcribe.parse import parse_ok
from transcribe.readings import page_pass

RAW_FRAME_CONFIDENCE = 0.6   # one reading, no crop, no geometry: never presented as sure
BAND_MARGIN = 0.04           # leave a little room top and bottom of the frame


def raw_frame_lines(frame_path: str, width: int, height: int, quality_cap: float) -> tuple[list[dict], list[dict]]:
    """(regions, lines) read from the whole frame, or ([], []) if the model read nothing."""
    with Timer("transcribe.rawframe") as t:
        readings = page_pass([{"path": frame_path, "bbox": None}]) or []
        readings = [r for r in readings if not r.get("illegible") and ((r.get("latex") or "").strip() or (r.get("text") or "").strip())]
        t.extra["lines"] = len(readings)
    if not readings or width <= 0 or height <= 0:
        return [], []
    top, usable = height * BAND_MARGIN, height * (1 - 2 * BAND_MARGIN)
    band = usable / len(readings)
    lines = []
    for i, r in enumerate(readings):
        spans, _ = model_spans(r)
        latex = r.get("latex") or ""
        lines.append(make_line(
            region_id="R0", order=i, bbox=[0.0, top + i * band, float(width), band],
            status="active", kind=r.get("kind") if r.get("kind") in ("math", "text", "mixed", "diagram_label") else "text",
            latex=latex, text=r.get("text") or "", confidence=min(RAW_FRAME_CONFIDENCE, quality_cap),
            uncertain_spans=spans, parse_ok=parse_ok(latex) if latex else False,
            extra={"bbox_estimated": True, "crop_hash": None, "crop_path": None, "context_crop_path": None,
                   "readings": {"page": r, "notes": ["raw_frame_page_pass"], "cached": False}, "latency_ms": {"page_pass": round(t.ms, 1)}}))
    return [{"id": "R0", "type": "work", "bbox": [0.0, 0.0, float(width), float(height)]}], lines
