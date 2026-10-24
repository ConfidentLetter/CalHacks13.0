"""build_twin: calibrate -> tile -> components -> wires (excluding component boxes) -> nets.

Every upstream call is wrapped: if T1 raises, the twin is still returned with what succeeded and
the failure is logged. The UI must never go blank.
"""
from __future__ import annotations

import copy
import hashlib
import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ._telemetry import log, timed
from .components import detect_components, mock_mode
from .geometry_bridge import IDENTITY, calibrate, hole_to_pixel
from .paths import MOCK_TWIN_OK_PATH
from .registration import set_current_homography
from .schema import validate_twin

BOARD_TYPE = "breadboard_830"
CACHE_SIZE = 8
_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()
_cache_generation = 0


def _frame_id(frame_path: str) -> str:
    """Stable id for a frame: sha1 of file bytes if it exists, else of the path string."""
    p = Path(frame_path)
    h = hashlib.sha1()
    h.update(p.read_bytes() if p.is_file() else str(frame_path).encode("utf-8"))
    return "f_" + h.hexdigest()[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def mock_twin(frame_path: str) -> dict:
    """Content of mocks/twin_ok.json with a fresh frame_id and timestamp."""
    base = json.loads(MOCK_TWIN_OK_PATH.read_text())
    return {**copy.deepcopy(base), "frame_id": _frame_id(frame_path), "timestamp": _now_iso()}


def _guarded(stage: str, fn: Callable[[], Any], default: Any, errors: dict, **extra) -> Any:
    """Run one pipeline stage; on exception log it, record it, and return `default`."""
    with timed(stage, **extra) as info:
        try:
            return fn()
        except Exception as exc:  # another terminal's half-written code must not blank the UI
            msg = f"{type(exc).__name__}: {exc}"[:200]
            info["error"] = msg
            errors[stage] = msg
            return default


def _geometry():
    import perception_geometry as g  # type: ignore

    return g


def _clamp01(v: Any, default: float = 0.5) -> float:
    try:
        return min(1.0, max(0.0, float(v)))
    except (TypeError, ValueError):
        return default


def _end(e: dict, H: Any) -> dict:
    """A wire end with a usable pixel: the given one, else the hole centre, else [0, 0]."""
    px = e.get("pixel")
    ok = isinstance(px, (list, tuple)) and len(px) == 2 and all(isinstance(v, (int, float)) for v in px)
    if not ok or list(px) == [0, 0]:
        centre = hole_to_pixel(e["hole"], H) if e.get("hole") else None
        px = list(centre) if centre else [0.0, 0.0]
    return {**e, "hole": e.get("hole"), "pixel": [float(px[0]), float(px[1])]}


def _valid_wires(wires: Any, H: Any) -> list[dict]:
    """Coerce whatever T1 returned into schema-valid wires; silently drop the rest."""
    out = []
    for w in wires if isinstance(wires, list) else []:
        try:
            ends = [w.get("end_a"), w.get("end_b")]
            if not all(isinstance(e, dict) and "hole" in e for e in ends):
                continue
            out.append({**w, "end_a": _end(ends[0], H), "end_b": _end(ends[1], H),
                        "confidence": _clamp01(w.get("confidence")), "color": str(w.get("color", "")),
                        "id": str(w.get("id") or f"w_{len(out) + 1}")})
        except Exception:
            continue
    return out


def _assemble(frame_path: str, H: list[list[float]], components: list[dict], wires: list[dict],
              nets: list[dict]) -> dict:
    return {
        "frame_id": _frame_id(frame_path),
        "timestamp": _now_iso(),
        "board": {"type": BOARD_TYPE, "homography": H},
        "components": components,
        "wires": wires,
        "nets": nets if isinstance(nets, list) else [],
    }


def _sanitize(twin: dict) -> dict:
    """Last line of defence: drop the offending section rather than crash."""
    problems = validate_twin(twin)
    if not problems:
        return twin
    log("twin.invalid", 0.0, problems=problems[:5])
    if any(p.startswith("board") for p in problems):
        twin = {**twin, "board": {"type": BOARD_TYPE, "homography": [r[:] for r in IDENTITY]}}
    dropped = [k for k in ("components", "wires") if any(p.startswith(k) for p in problems)]
    if dropped or any(p.startswith("nets") for p in problems):
        twin = {**twin, **{k: [] for k in dropped}, "nets": []}   # nets refer to dropped parts
    if validate_twin(twin):   # still bad: strip everything but the frame
        twin = {**twin, "components": [], "wires": [], "nets": []}
    return twin


def _pipeline(frame_path: str) -> dict:
    errors: dict[str, str] = {}
    cal = calibrate(frame_path)
    H = cal.homography
    if cal.error:
        errors["calibrate"] = cal.error
        log("calibrate", 0.0, error=cal.error, fallback=cal.source)
    set_current_homography(H, calibrated=cal.calibrated)

    tiles = _guarded("tile", lambda: _geometry().tile(frame_path, H), [], errors)
    components = _guarded("components", lambda: detect_components(
        frame_path, tiles, homography=H, calibrated=cal.calibrated), [], errors)
    boxes = [c["bbox"] for c in components]
    wires = _guarded("wires", lambda: _valid_wires(
        _geometry().detect_wires(frame_path, H, exclude_boxes=boxes), H), [], errors)
    nets = _guarded("nets", lambda: _geometry().build_nets(components, wires), [], errors)

    twin = _sanitize(_assemble(frame_path, H, components, wires, nets))
    twin = {**twin, "calibration": cal.source}
    if errors:
        twin = {**twin, "errors": errors}
    return twin


def build_twin(frame_path: str) -> dict:
    """calibrate -> tile -> components -> wires (excluding component boxes) -> nets. twin.schema.json.

    BM_MOCK=1 returns mocks/twin_ok.json with a fresh frame_id/timestamp. Results are cached by
    frame hash (registrations change the result, so registering clears the cache)."""
    with timed("build_twin", frame=Path(frame_path).name) as info:
        if mock_mode():
            info["mock"] = True
            twin = mock_twin(frame_path)
        else:
            fid = _frame_id(frame_path)
            with _cache_lock:
                cached = _cache.get(fid)
                gen = _cache_generation
            if cached is not None:
                info["cached"] = True
                return copy.deepcopy(cached)
            twin = _pipeline(frame_path)
            with _cache_lock:
                if gen == _cache_generation:   # no register/calibrate happened meanwhile
                    _cache[fid] = copy.deepcopy(twin)
                    while len(_cache) > CACHE_SIZE:
                        _cache.pop(next(iter(_cache)))
        info["components"] = len(twin["components"])
        info["wires"] = len(twin["wires"])
        info["nets"] = len(twin["nets"])
    return twin


def clear_cache() -> None:
    """Forget cached twins (called on register / manual calibrate; T5 may call it too)."""
    global _cache_generation
    with _cache_lock:
        _cache.clear()
        _cache_generation += 1
