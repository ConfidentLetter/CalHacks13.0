"""Tier A click-to-register: persist user clicks to runtime/registrations.json."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from ._telemetry import timed
from .paths import REGISTRATIONS_PATH

_CURRENT_HOMOGRAPHY_HASH: str | None = None


def homography_hash(homography: Any) -> str:
    """Short, stable hash of a 3x3 homography (rounded so float noise does not invalidate clicks)."""
    try:
        rows = [[round(float(v), 4) for v in row] for row in homography]
    except Exception:
        rows = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    return hashlib.sha1(json.dumps(rows).encode("utf-8")).hexdigest()[:12]


def set_current_homography(homography: Any | None) -> None:
    """Called by build_twin after calibration so new registrations carry the right hash."""
    global _CURRENT_HOMOGRAPHY_HASH
    _CURRENT_HOMOGRAPHY_HASH = None if homography is None else homography_hash(homography)


def current_homography_hash() -> str | None:
    return _CURRENT_HOMOGRAPHY_HASH


def load_registrations(path: Path = REGISTRATIONS_PATH) -> list[dict]:
    """All registrations, oldest first. Missing or corrupt file -> []."""
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text())
    except Exception:
        return []
    if isinstance(data, dict):
        data = data.get("registrations", [])
    return [r for r in data if isinstance(r, dict)]


def _atomic_write(path: Path, data: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".reg_", suffix=".json")
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)


def save_registrations(regs: list[dict], path: Path = REGISTRATIONS_PATH) -> None:
    _atomic_write(path, regs)


def register(part_id: str, row_index: int, pixel: tuple[float, float],
             *, end_pixel: tuple[float, float] | None = None,
             path: Path = REGISTRATIONS_PATH) -> None:
    """Tier A: user clicked the first pin of footprint row `row_index` of `part_id`.

    Persists {part_id, row_index, pixel, end_pixel, homography_hash} to runtime/registrations.json.
    A second registration for the same (part_id, row_index) replaces the first.
    `end_pixel` (optional, extra kwarg) is a click on the LAST pin of the row to fix direction.
    """
    if not isinstance(part_id, str) or not part_id.strip():
        raise ValueError("part_id must be a non-empty string")
    if not isinstance(row_index, int) or row_index < 0:
        raise ValueError("row_index must be a non-negative int")
    try:
        px = [float(pixel[0]), float(pixel[1])]
    except Exception as exc:
        raise ValueError(f"pixel must be (x, y), got {pixel!r}") from exc
    end = None
    if end_pixel is not None:
        end = [float(end_pixel[0]), float(end_pixel[1])]

    with timed("register", part_id=part_id, row_index=row_index):
        entry = {
            "part_id": part_id.strip(),
            "row_index": row_index,
            "pixel": px,
            "end_pixel": end,
            "homography_hash": _CURRENT_HOMOGRAPHY_HASH,
        }
        kept = [r for r in load_registrations(path)
                if not (r.get("part_id") == entry["part_id"] and r.get("row_index") == row_index)]
        save_registrations([*kept, entry], path)


def clear_registrations(path: Path = REGISTRATIONS_PATH) -> None:
    if path.is_file():
        path.unlink()


def is_stale(reg: dict, homography: Any | None) -> bool:
    """A registration is stale when it was made under a different calibration.
    Registrations with no hash (made before any calibration) are never stale."""
    saved = reg.get("homography_hash")
    if saved is None or homography is None:
        return False
    return saved != homography_hash(homography)
