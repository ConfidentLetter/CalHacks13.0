"""Stills coming from the frontend: base64 → runtime/uploads/<id>.jpg, plus the snapshot object the UI expects."""
from __future__ import annotations

import base64
import os
import re
import threading
from pathlib import Path
from typing import Any

from bridge.compat import RUNTIME_DIR, file_url, new_id, now_iso, repo_relative

UPLOAD_DIR = Path(os.environ.get("SV_UPLOAD_DIR", RUNTIME_DIR / "uploads"))
MAX_IMAGE_BYTES = 12 * 1024 * 1024
_DATA_URL = re.compile(r"^data:[^;,]+;base64,", re.I)
_MAGIC = {b"\xff\xd8\xff": ".jpg", b"\x89PNG": ".png", b"RIFF": ".webp"}


class ImageError(ValueError):
    """The client sent something that is not a usable image."""


def decode_base64_image(raw: str) -> tuple[bytes, str]:
    """Return (bytes, extension). Accepts a bare base64 string or a data: URL."""
    if not isinstance(raw, str) or not raw.strip():
        raise ImageError("image.base64 is empty")
    body = _DATA_URL.sub("", raw.strip())
    try:
        data = base64.b64decode(body, validate=False)
    except (ValueError, TypeError) as exc:
        raise ImageError("image.base64 is not valid base64") from exc
    if not data:
        raise ImageError("image.base64 decoded to nothing")
    if len(data) > MAX_IMAGE_BYTES:
        raise ImageError(f"image is too large ({len(data) // 1024} KB; max {MAX_IMAGE_BYTES // 1024} KB)")
    ext = next((e for magic, e in _MAGIC.items() if data.startswith(magic)), None)
    if ext is None:
        raise ImageError("image.base64 is not a JPEG, PNG or WebP")
    return data, ext


def save_still(data: bytes, ext: str = ".jpg", prefix: str = "still") -> tuple[str, str]:
    """Write bytes under runtime/uploads/; returns (id, repo-relative path)."""
    still_id = new_id(prefix)
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = UPLOAD_DIR / f"{still_id}{ext}"
    path.write_bytes(data)
    return still_id, repo_relative(path)


# ---------------------------------------------------------------------- still index
# Stills the bridge took or received, by id, so `image.snapshotId` can be resolved without a twin.

_index: dict[str, dict] = {}
_index_lock = threading.Lock()
_latest_id: str | None = None
MAX_INDEX = 200


def register_still(still_id: str, path: str, source: str, captured_at: str | None = None) -> dict:
    """Remember a still; returns its snapshot object (frontend shape)."""
    global _latest_id
    entry = {"id": still_id, "path": repo_relative(path), "source": source, "capturedAt": captured_at or now_iso()}
    with _index_lock:
        _index[still_id] = entry
        _latest_id = still_id
        if len(_index) > MAX_INDEX:
            for old in sorted(_index, key=lambda k: _index[k]["capturedAt"])[: len(_index) - MAX_INDEX]:
                _index.pop(old, None)
    return snapshot_object(entry)


def lookup_still(still_id: str) -> dict | None:
    with _index_lock:
        entry = _index.get(still_id)
    return dict(entry) if entry else None


def latest_still() -> dict | None:
    with _index_lock:
        entry = _index.get(_latest_id) if _latest_id else None
    return dict(entry) if entry else None


def reset_index() -> None:
    global _latest_id
    with _index_lock:
        _index.clear()
        _latest_id = None


def snapshot_object(entry: dict) -> dict:
    """`{id, imageUrl, capturedAt, deviceId}` as the frontend's normalizeSnapshot expects."""
    return {"id": entry["id"], "imageUrl": file_url(entry.get("path")), "capturedAt": entry.get("capturedAt"),
            "deviceId": entry.get("source") or "unknown"}


def snapshot_from_twin(twin: dict | None) -> dict | None:
    """The same object for an analysed twin (None for the mock fallback or no twin)."""
    if not twin or twin.get("_fallback"):
        return None
    image: dict[str, Any] = twin.get("image") or {}
    return {"id": twin.get("snapshot_id"), "imageUrl": file_url(image.get("original_path")),
            "capturedAt": twin.get("captured_at"), "deviceId": twin.get("source") or "unknown",
            "dewarpedUrl": file_url(image.get("dewarped_path")), "lineCount": len(twin.get("lines") or [])}
