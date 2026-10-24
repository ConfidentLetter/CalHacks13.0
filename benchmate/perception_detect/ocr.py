"""Read the printed markings on a component crop with the vision model.

The model is used ONLY to read text and say whether it is legible. It is never asked for
coordinates and never asked to guess what the part "might be".
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import threading

from ._telemetry import log, timed

DEFAULT_MODEL = "claude-sonnet-5-5"
CROP_PAD = 0.20            # pad the bbox by 20 % on each side
MIN_CROP_PX = 256          # upscale 2x when the crop's longer side is below this
MAX_TOKENS = 256
JPEG_QUALITY = 90
API_TIMEOUT_S = 8.0
API_MAX_RETRIES = 1
CACHE_PX = 24              # labels are cached per bbox quantized to this many pixels (fixed camera)
CACHE_MAX = 64
_label_cache: dict[tuple, dict | None] = {}
_cache_lock = threading.Lock()

PROMPT = (
    "This is a photo crop of one electronic module on a breadboard. Read the printed text on the "
    "module (silkscreen labels, part numbers, markings). Report only characters you can actually "
    "see; do not guess what the part might be or complete partial words. Respond with strict JSON "
    'and nothing else: {"text": "<all legible printed text, space separated>", "legible": true|false}. '
    "Set legible=false if you cannot read any marking clearly."
)
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def model_name() -> str:
    return os.environ.get("BM_MODEL", "").strip() or DEFAULT_MODEL


def crop_component(frame_path: str, bbox: list[float]) -> bytes | None:
    """JPEG bytes of the padded (and, if small, 2x upscaled) crop; None if the image can't be read."""
    import cv2

    img = cv2.imread(str(frame_path))
    if img is None:
        return None
    h_img, w_img = img.shape[:2]
    x, y, w, h = bbox
    px, py = w * CROP_PAD, h * CROP_PAD
    x0, y0 = int(max(0, x - px)), int(max(0, y - py))
    x1, y1 = int(min(w_img, x + w + px)), int(min(h_img, y + h + py))
    if x1 <= x0 or y1 <= y0:
        return None
    crop = img[y0:y1, x0:x1]
    if max(crop.shape[:2]) < MIN_CROP_PX:
        crop = cv2.resize(crop, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
    ok, buf = cv2.imencode(".jpg", crop, [int(cv2.IMWRITE_JPEG_QUALITY), JPEG_QUALITY])
    return bytes(buf) if ok else None


def parse_label_json(text: str) -> dict | None:
    """Tolerant parse of the model's reply -> {"text": str, "legible": bool} or None."""
    m = _JSON_RE.search(text or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    label = str(data.get("text") or "").strip()
    legible = bool(data.get("legible")) and bool(label)
    return {"text": label, "legible": legible}


def _client() -> Any | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        import anthropic

        return anthropic.Anthropic(timeout=API_TIMEOUT_S, max_retries=API_MAX_RETRIES)
    except Exception as exc:
        log("ocr.error", 0.0, error=f"client: {type(exc).__name__}: {exc}"[:160])
        return None


def ask_model(jpeg: bytes, client: Any | None = None) -> str | None:
    """One vision request; returns the raw text reply or None on any failure/refusal."""
    client = client or _client()
    if client is None:
        return None
    try:
        resp = client.messages.create(
            model=model_name(),
            max_tokens=MAX_TOKENS,
            output_config={"effort": "low"},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                             "data": base64.standard_b64encode(jpeg).decode("ascii")}},
                {"type": "text", "text": PROMPT},
            ]}],
        )
    except Exception as exc:
        log("ocr.error", 0.0, error=f"{type(exc).__name__}: {exc}"[:160], model=model_name())
        return None
    if getattr(resp, "stop_reason", None) == "refusal":
        log("ocr.error", 0.0, error="refusal", model=model_name())
        return None
    return "".join(getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text")


def _cache_key(bbox: list[float]) -> tuple:
    return tuple(int(round(v / CACHE_PX)) for v in bbox)


def clear_label_cache() -> None:
    with _cache_lock:
        _label_cache.clear()


def read_label(frame_path: str, bbox: list[float], client: Any | None = None) -> dict | None:
    """{"text": ..., "legible": bool} for the component in bbox, or None if nothing legible / no API.
    Cached by quantized bbox: on a fixed camera a part that stays put is read once, not every frame."""
    key = _cache_key(bbox)
    with _cache_lock:
        if key in _label_cache:
            return _label_cache[key]
    result = _read_label_uncached(frame_path, bbox, client)
    with _cache_lock:
        if len(_label_cache) >= CACHE_MAX:
            _label_cache.clear()
        if result is not None or client is not None:   # don't cache "no API key" forever
            _label_cache[key] = result
    return result


def _read_label_uncached(frame_path: str, bbox: list[float], client: Any | None = None) -> dict | None:
    with timed("ocr.read_label", frame=Path(frame_path).name) as info:
        jpeg = crop_component(frame_path, bbox)
        if jpeg is None:
            info["reason"] = "no crop"
            return None
        reply = ask_model(jpeg, client)
        if reply is None:
            info["reason"] = "no model reply"
            return None
        parsed = parse_label_json(reply)
        if parsed is None:
            info["reason"] = "unparseable reply"
            return None
        info["legible"] = parsed["legible"]
        return parsed if parsed["legible"] else None
