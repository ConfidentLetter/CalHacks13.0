"""Tier A: registered clicks + profile footprints -> twin components."""
from __future__ import annotations

from typing import Any

from ._telemetry import log
from .geometry_bridge import hole_to_pixel, parse_hole, pitch_px
from .layout import RowLayout, layout_row
from .profiles import get_profile
from .registration import is_stale, load_registrations, resolve_holes

BBOX_PAD_PITCHES = 1.5
TIER_A_CONFIDENCE = 0.99


def component_id(part_id: str, n: int) -> str:
    """'esp32-devkitc', 1 -> 'esp32_1' (matches the mock twins)."""
    return f"{part_id.split('-')[0]}_{n}"


def _bbox_from_pins(holes: list[str | None], homography: Any) -> list[float]:
    pts = [p for h in holes if h and (p := hole_to_pixel(h, homography))]
    if not pts:
        return [0.0, 0.0, 0.0, 0.0]
    pad = BBOX_PAD_PITCHES * pitch_px(homography)
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    x0, y0 = min(xs) - pad, min(ys) - pad
    return [round(x0, 1), round(y0, 1), round(max(xs) + pad - x0, 1), round(max(ys) + pad - y0, 1)]


def _layout_registered_rows(part_id: str, regs: list[dict], homography: Any,
                            calibrated: bool = True) -> list[RowLayout]:
    rows = get_profile(part_id).get("footprint", {}).get("rows", [])
    layouts: list[RowLayout] = []
    reference: tuple[int, int] | None = None
    for reg in sorted(regs, key=lambda r: r["row_index"]):
        idx = reg["row_index"]
        if idx >= len(rows):
            log("tier_a.skip", 0.0, part_id=part_id, row_index=idx, reason="no such footprint row")
            continue
        anchor, end = resolve_holes(reg, homography, calibrated=calibrated)
        if anchor is None or parse_hole(anchor) is None:
            log("tier_a.skip", 0.0, part_id=part_id, row_index=idx,
                reason="click off-board" if calibrated else "not calibrated")
            continue
        row = layout_row(list(rows[idx]["pins"]), anchor, end_hole=end, reference_columns=reference)
        layouts.append(row)
        reference = reference or row.columns
    return layouts


def tier_a_components(homography: Any, registrations: list[dict] | None = None, *,
                      calibrated: bool = True) -> list[dict]:
    """One component per registered part_id (all its registered rows merged), twin.schema.json shape.
    With calibrated=False (identity fallback) only registrations that already carry a hole are used."""
    regs = load_registrations() if registrations is None else registrations
    by_part: dict[str, list[dict]] = {}
    for r in regs:
        if isinstance(r.get("part_id"), str) and isinstance(r.get("row_index"), int):
            by_part.setdefault(r["part_id"], []).append(r)

    components: list[dict] = []
    counts: dict[str, int] = {}
    for part_id, part_regs in by_part.items():
        try:
            get_profile(part_id)
        except KeyError:
            log("tier_a.skip", 0.0, part_id=part_id, reason="no profile")
            continue
        try:
            layouts = _layout_registered_rows(part_id, part_regs, homography, calibrated)
        except Exception as exc:   # one bad registration must not take out the others
            log("tier_a.skip", 0.0, part_id=part_id, reason=f"{type(exc).__name__}: {exc}"[:120])
            continue
        if not layouts:
            continue
        pins = [{"name": n, "hole": h} for row in layouts for n, h in row.pins]
        counts[part_id] = counts.get(part_id, 0) + 1
        components.append({
            "id": component_id(part_id, counts[part_id]),
            "part_id": part_id,
            "label_text": "",
            "bbox": _bbox_from_pins([p["hole"] for p in pins], homography),
            "pins": pins,
            "confidence": TIER_A_CONFIDENCE,
            "source": "tier_a",
        })
    return components


def stale_registrations(homography: Any) -> list[dict]:
    """Registrations whose click pixel no longer maps to the hole it was registered on (camera or
    part moved). They are still used; T5 may prompt the user to confirm or click again."""
    return [r for r in load_registrations() if is_stale(r, homography)]
