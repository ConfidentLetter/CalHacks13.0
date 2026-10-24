"""Tier A click-to-register: persist user clicks to runtime/registrations.json.

The invariant of a registration is the HOLE the click snapped to, not the pixel: a component sits
on the board, so if the camera (and therefore the homography) drifts between frames the hole is
still right. The pixel is kept for re-snapping when the click was made before any calibration.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from ._telemetry import log, timed
from .paths import registrations_path

_FILE_LOCK = threading.Lock()
_CURRENT_H: Any | None = None
_CURRENT_CALIBRATED: bool = False


def homography_hash(homography: Any) -> str:
    """Short, stable hash of a 3x3 homography (rounded so float noise does not change it)."""
    try:
        rows = [[round(float(v), 4) for v in row] for row in homography]
    except Exception:
        rows = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    return hashlib.sha1(json.dumps(rows).encode("utf-8")).hexdigest()[:12]


def set_current_homography(homography: Any | None, *, calibrated: bool = True) -> None:
    """Called by build_twin after calibration. calibrated=False means an identity fallback, under
    which clicks must not be snapped to holes (they would be nonsense)."""
    global _CURRENT_H, _CURRENT_CALIBRATED
    _CURRENT_H = None if homography is None else [list(map(float, r)) for r in homography]
    _CURRENT_CALIBRATED = bool(calibrated and homography is not None)


def current_homography() -> Any | None:
    return _CURRENT_H


def current_homography_hash() -> str | None:
    return None if _CURRENT_H is None else homography_hash(_CURRENT_H)


def load_registrations(path: Path | None = None) -> list[dict]:
    """All registrations, oldest first. Missing or corrupt file -> []."""
    path = path or registrations_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("registrations", [])
    if not isinstance(data, list):
        return []
    return [r for r in data if _valid_entry(r)]


def _valid_entry(r: Any) -> bool:
    try:
        return (isinstance(r, dict) and isinstance(r["part_id"], str) and isinstance(r["row_index"], int)
                and len(r["pixel"]) == 2 and all(isinstance(v, (int, float)) for v in r["pixel"]))
    except (KeyError, TypeError):
        return False


def _atomic_write(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".reg_", suffix=".json")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def save_registrations(regs: list[dict], path: Path | None = None) -> None:
    _atomic_write(path or registrations_path(), regs)


def _snap(pixel: list[float] | None) -> str | None:
    if pixel is None or not _CURRENT_CALIBRATED or _CURRENT_H is None:
        return None
    from .geometry_bridge import snap_to_hole

    return snap_to_hole((pixel[0], pixel[1]), _CURRENT_H)


def register(part_id: str, row_index: int, pixel: tuple[float, float],
             *, end_pixel: tuple[float, float] | None = None,
             path: Path | None = None) -> None:
    """Tier A: user clicked the first pin of footprint row `row_index` of `part_id`.

    Persists {part_id, row_index, pixel, hole, end_pixel, end_hole, homography_hash} to
    runtime/registrations.json. A second registration for the same (part_id, row_index) replaces
    the first. `end_pixel` (optional extra kwarg) is a click on the LAST pin of the row.
    """
    if not isinstance(part_id, str) or not part_id.strip():
        raise ValueError("part_id must be a non-empty string")
    if not isinstance(row_index, int) or row_index < 0:
        raise ValueError("row_index must be a non-negative int")
    try:
        px = [float(pixel[0]), float(pixel[1])]
    except Exception as exc:
        raise ValueError(f"pixel must be (x, y), got {pixel!r}") from exc
    end = None if end_pixel is None else [float(end_pixel[0]), float(end_pixel[1])]
    path = path or registrations_path()

    with timed("register", part_id=part_id, row_index=row_index) as info:
        entry = {
            "part_id": part_id.strip(),
            "row_index": row_index,
            "pixel": px,
            "hole": _snap(px),
            "end_pixel": end,
            "end_hole": _snap(end),
            "homography_hash": current_homography_hash(),
        }
        info["hole"] = entry["hole"]
        with _FILE_LOCK:
            kept = [r for r in load_registrations(path)
                    if not (r.get("part_id") == entry["part_id"] and r.get("row_index") == row_index)]
            save_registrations([*kept, entry], path)
    _invalidate_twin_cache()


def _invalidate_twin_cache() -> None:
    try:
        from .twin import clear_cache

        clear_cache()
    except Exception:
        pass


def clear_registrations(path: Path | None = None) -> None:
    path = path or registrations_path()
    if path.is_file():
        path.unlink()


def resolve_holes(reg: dict, homography: Any, *, calibrated: bool = True) -> tuple[str | None, str | None]:
    """(anchor_hole, end_hole) for a registration under `homography`: the stored hole wins; a
    click made before calibration is snapped now (never under an uncalibrated identity)."""
    from .geometry_bridge import snap_to_hole

    def one(hole_key: str, px_key: str) -> str | None:
        if reg.get(hole_key):
            return reg[hole_key]
        px = reg.get(px_key)
        return snap_to_hole((px[0], px[1]), homography) if (px and calibrated) else None

    return one("hole", "pixel"), one("end_hole", "end_pixel")


def is_stale(reg: dict, homography: Any | None) -> bool:
    """True when the registration was made under a different calibration AND its click pixel no
    longer snaps to the stored hole (camera moved, or the part was moved without re-registering).
    Stale registrations are still USED (the hole is the invariant); this only drives a UI hint."""
    if homography is None or not reg.get("hole") or reg.get("homography_hash") is None:
        return False
    if reg["homography_hash"] == homography_hash(homography):
        return False
    from .geometry_bridge import snap_to_hole

    px = reg.get("pixel")
    now = snap_to_hole((px[0], px[1]), homography) if px else None
    if now != reg["hole"]:
        log("register.stale", 0.0, part_id=reg.get("part_id"), row_index=reg.get("row_index"),
            was=reg["hole"], now=now)
        return True
    return False
