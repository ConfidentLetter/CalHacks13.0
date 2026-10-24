"""Image preparation for the vision model: downscaled full frame + close-up tiles. Pure functions."""
from __future__ import annotations

import base64
import io
from pathlib import Path
from typing import Any

MAX_LONG_SIDE = 1568
TILE_HALF = 110          # px around a point of interest in the original frame
TILE_MIN_SIDE = 320      # upscale small crops to at least this
MAX_TILES = 4
JPEG_QUALITY = 85


def _open(frame_path: str | None):
    if not frame_path or not Path(frame_path).is_file():
        return None
    try:
        from PIL import Image
        img = Image.open(frame_path)
        img.load()
        return img.convert("RGB")
    except Exception:
        return None


def _to_block(img) -> dict[str, Any]:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=JPEG_QUALITY)
    data = base64.standard_b64encode(buf.getvalue()).decode("ascii")
    return {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}}


def full_frame_block(frame_path: str | None) -> dict[str, Any] | None:
    img = _open(frame_path)
    if img is None:
        return None
    w, h = img.size
    scale = min(1.0, MAX_LONG_SIDE / max(w, h))
    if scale < 1.0:
        from PIL import Image
        img = img.resize((max(1, int(w * scale)), max(1, int(h * scale))), Image.LANCZOS)
    return _to_block(img)


def points_of_interest(twin: dict[str, Any], threshold: float) -> list[tuple[str, float, float]]:
    """(element_id, x, y) for every low-confidence wire end and component centre."""
    pts: list[tuple[str, float, float]] = []
    for w in twin.get("wires", []):
        if float(w.get("confidence", 1.0)) < threshold:
            for end in (w.get("end_a"), w.get("end_b")):
                px = (end or {}).get("pixel") or []
                if len(px) == 2:
                    pts.append((w["id"], float(px[0]), float(px[1])))
    for c in twin.get("components", []):
        if float(c.get("confidence", 1.0)) < threshold and len(c.get("bbox") or []) == 4:
            x, y, bw, bh = c["bbox"]
            pts.append((c["id"], float(x) + float(bw) / 2, float(y) + float(bh) / 2))
    return pts


def tile_blocks(frame_path: str | None, twin: dict[str, Any], threshold: float) -> list[tuple[str, dict[str, Any]]]:
    """Close-up crops around low-confidence elements: [(element_id, image_block)]."""
    img = _open(frame_path)
    if img is None:
        return []
    from PIL import Image
    w, h = img.size
    out: list[tuple[str, dict[str, Any]]] = []
    seen: set[tuple[int, int]] = set()
    for eid, x, y in points_of_interest(twin, threshold):
        key = (int(x) // TILE_HALF, int(y) // TILE_HALF)
        if key in seen or (x == 0 and y == 0):
            continue
        seen.add(key)
        box = (max(0, int(x - TILE_HALF)), max(0, int(y - TILE_HALF)), min(w, int(x + TILE_HALF)), min(h, int(y + TILE_HALF)))
        if box[2] - box[0] < 8 or box[3] - box[1] < 8:
            continue
        crop = img.crop(box)
        if max(crop.size) < TILE_MIN_SIDE:
            f = TILE_MIN_SIDE / max(crop.size)
            crop = crop.resize((int(crop.size[0] * f), int(crop.size[1] * f)), Image.LANCZOS)
        out.append((eid, _to_block(crop)))
        if len(out) >= MAX_TILES:
            break
    return out
