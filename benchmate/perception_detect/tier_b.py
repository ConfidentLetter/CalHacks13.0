"""Tier B: OWLv2 boxes on T1's tiles -> label text -> part_id -> pin layout (no click needed)."""
from __future__ import annotations

from typing import Any, Callable

from ._telemetry import log, timed
from .boxes import nms, to_original
from .config import (MAX_COMPONENT_BOARD_FRACTION, MAX_COMPONENT_PITCHES, NMS_IOU, OWL_IGNORE_QUERIES,
                     OWL_SCORE_THRESHOLD, TIER_B_CONFIDENCE_CAP)
from .geometry_bridge import hole_to_pixel, parse_hole, pitch_px, snap_to_hole
from .layout import layout_row
from .normalize import normalize_part
from .ocr import read_label
from .owl import Detection
from .profiles import get_profile

ANCHOR_TOLERANCE_PITCHES = 1.2
Detector = Callable[[Any], list[Detection]]


def component_sized(bbox: tuple[float, float, float, float], homography: Any | None) -> bool:
    """False for boxes wider/taller than any component can be (in breadboard pitches)."""
    if homography is None:
        return True
    p = pitch_px(homography)
    return bbox[2] <= MAX_COMPONENT_PITCHES[0] * p and bbox[3] <= MAX_COMPONENT_PITCHES[1] * p


def detect_boxes(frame_path: str, tiles: list[dict] | None, detector: Detector,
                 frame_size: tuple[int, int] | None = None, homography: Any | None = None) -> list[Detection]:
    """Run the detector per tile (or the full frame), map to original pixels, NMS, drop board-sized boxes."""
    tiles = tiles or [{"path": frame_path, "bbox": [0, 0, 0, 0], "scale": 1.0}]
    dets: list[Detection] = []
    for t in tiles:
        with timed("tier_b.tile", tile=str(t.get("path", ""))[-24:]) as info:
            try:
                found = detector(t["path"])
            except Exception as exc:
                info["error"] = f"{type(exc).__name__}: {exc}"[:120]
                continue
            dets.extend(to_original(d, t) for d in found if d.label not in OWL_IGNORE_QUERIES)
    kept = nms(dets, NMS_IOU)
    if frame_size:
        area = float(frame_size[0] * frame_size[1])
        kept = [d for d in kept if d.bbox[2] * d.bbox[3] / area <= MAX_COMPONENT_BOARD_FRACTION]
    kept = [d for d in kept if component_sized(d.bbox, homography)]
    return [d for d in kept if d.score >= OWL_SCORE_THRESHOLD]


def _channel_y_at(x: float, homography: Any) -> float | None:
    """y of the centre channel (between rows E and F) at the column nearest x."""
    e, f = hole_to_pixel("E32", homography), hole_to_pixel("F32", homography)
    return (e[1] + f[1]) / 2 if e and f else None


def anchor_pins(bbox: tuple[float, float, float, float], rows: list[dict], homography: Any) -> list[dict] | None:
    """Pins for a detected box without a click: row 0 on the box edge nearest the centre channel,
    row 1 (if any) on the opposite edge, first pin at the left end, direction from the right end.
    None if any pin lands off-board (caller asks for a register click instead)."""
    x, y, w, h = bbox
    half = 0.5 * pitch_px(homography)
    cy = _channel_y_at(x + w / 2, homography)
    top, bottom = y + half, y + h - half
    edges = [top, bottom] if cy is None or abs(top - cy) <= abs(bottom - cy) else [bottom, top]
    tol = ANCHOR_TOLERANCE_PITCHES * pitch_px(homography)
    pins: list[dict] = []
    for idx, row in enumerate(rows[:2]):
        ey = edges[idx]
        start = snap_to_hole((x + half, ey), homography, tolerance_px=tol)
        end = snap_to_hole((x + w - half, ey), homography, tolerance_px=tol)
        if start is None or parse_hole(start) is None:
            return None
        laid = layout_row(list(row["pins"]), start, end_hole=end)
        if any(hole is None for _, hole in laid.pins):
            return None
        pins.extend({"name": n, "hole": hole} for n, hole in laid.pins)
    return pins


def tier_b_components(frame_path: str, tiles: list[dict] | None, homography: Any, *,
                      detector: Detector, reader: Callable[[str, list[float]], dict | None] = read_label,
                      frame_size: tuple[int, int] | None = None,
                      calibrated: bool = True) -> tuple[list[dict], list[dict]]:
    """(components, needs_register). Components without a readable/known part_id are still returned
    (part_id None, no pins) so the UI can draw the box and ask the user to register it."""
    boxes = detect_boxes(frame_path, tiles, detector, frame_size, homography)
    components: list[dict] = []
    needs_register: list[dict] = []
    counts: dict[str, int] = {}
    for n, d in enumerate(boxes, 1):
        bbox = [round(v, 1) for v in d.bbox]
        label = reader(frame_path, bbox)
        text = label["text"] if label else ""
        part_id = normalize_part(text) if text else None
        pins: list[dict] = []
        if part_id and calibrated:   # never snap pins under an uncalibrated identity homography
            try:
                rows = get_profile(part_id).get("footprint", {}).get("rows", [])
            except KeyError:
                rows = []
            pins = anchor_pins(d.bbox, rows, homography) or []
        prefix = part_id.split("-")[0] if part_id else "part"
        counts[prefix] = counts.get(prefix, 0) + 1
        cid = f"{prefix}_{counts[prefix]}"
        comp = {"id": cid, "part_id": part_id, "label_text": text, "bbox": bbox, "pins": pins,
                "confidence": round(min(TIER_B_CONFIDENCE_CAP, d.score), 3), "source": "tier_b",
                "detector_label": d.label}
        components.append(comp)
        if not pins:
            why = "unknown part" if not part_id else ("not calibrated" if not calibrated else "pins off-board")
            needs_register.append({"element_id": cid, "prompt": f"Click the first pin of {part_id or 'this part'} ({why})"})
            log("tier_b.needs_register", 0.0, element_id=cid, part_id=part_id, reason=why)
    return components, needs_register


def _overlap_of_smaller(a: list[float], b: list[float]) -> float:
    """Intersection area over the smaller box's area (a tight Tier A box inside a big OWL box -> 1)."""
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0.0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0.0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    smaller = min(aw * ah, bw * bh)
    return ix * iy / smaller if smaller > 0 else 0.0


def merge_tiers(tier_a: list[dict], tier_b: list[dict]) -> list[dict]:
    """Registered components always override Tier B for the same part_id; Tier B boxes that cover
    a registered component are dropped too; ids never collide across tiers."""
    taken = {c["part_id"] for c in tier_a if c.get("part_id")}
    used_ids = {c["id"] for c in tier_a}
    out = list(tier_a)
    for c in tier_b:
        if c.get("part_id") in taken:
            continue
        if any(_overlap_of_smaller(list(c["bbox"]), list(a["bbox"])) >= 0.5 for a in tier_a):
            continue
        cid, n = c["id"], 1
        while cid in used_ids:
            n += 1
            cid = f"{c['id'].rsplit('_', 1)[0]}_{n}"
        used_ids.add(cid)
        out.append({**c, "id": cid})
    return out
