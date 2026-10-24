"""Twin store: runtime/twins/<snapshot_id>.json plus an in-memory latest pointer."""
from __future__ import annotations

import json
import os
import re
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TWINS_DIR = Path(os.environ.get("SV_TWINS_DIR", ROOT / "runtime" / "twins"))

_lock = threading.Lock()
_latest: dict | None = None
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")


def _path(snapshot_id: str) -> Path | None:
    if not _SAFE_ID.match(snapshot_id):
        return None
    return TWINS_DIR / f"{snapshot_id}.json"


def save(twin: dict) -> Path:
    """Persist a twin and make it the latest. Returns the file path."""
    global _latest
    p = _path(str(twin.get("snapshot_id", "")))
    if p is None:
        raise ValueError(f"unsafe snapshot_id: {twin.get('snapshot_id')!r}")
    with _lock:
        TWINS_DIR.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(twin, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(p)
        (TWINS_DIR / "latest.json").write_text(json.dumps({"snapshot_id": twin["snapshot_id"]}), encoding="utf-8")
        _latest = twin
    return p


def latest() -> dict | None:
    """Most recent twin: in-memory if available, else re-read from disk (survives restarts)."""
    global _latest
    with _lock:
        if _latest is not None:
            return _latest
    try:
        sid = json.loads((TWINS_DIR / "latest.json").read_text(encoding="utf-8"))["snapshot_id"]
    except (OSError, ValueError, KeyError):
        return None
    twin = get(sid)
    with _lock:
        _latest = twin
    return twin


def get(snapshot_id: str) -> dict | None:
    p = _path(snapshot_id)
    if p is None or not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def list_ids() -> list[str]:
    """Snapshot ids on disk, oldest first (by mtime)."""
    if not TWINS_DIR.exists():
        return []
    files = [p for p in TWINS_DIR.glob("*.json") if p.name != "latest.json"]
    return [p.stem for p in sorted(files, key=lambda p: p.stat().st_mtime)]


def reset() -> None:
    """Forget the in-memory latest (tests)."""
    global _latest
    with _lock:
        _latest = None
