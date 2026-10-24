"""Read-only accessors for processes that embed app.server (T5's bridge).

Nothing here opens the camera or runs the model; it reads what the server has already produced.

    from app import bridge_api
    bridge_api.latest_twin()        -> dict | None   the latest page twin (as /twin/latest)
    bridge_api.latest_snapshot()    -> dict | None   {snapshot_id, captured_at, source, path, dewarped_path, image_url, ...}
    bridge_api.latest_frame_path()  -> str | None    newest still under runtime/snapshots/ (even if not yet analysed)
    bridge_api.file_url(path)       -> str           the /files/... URL the viewer uses for a repo-relative path
    await app.server.analyze(path, source)           run the pipeline on a still, store + broadcast on /events, return the twin
    app.pipeline.set_frame_provider(fn)              let the bridge supply stills so the camera is opened once
"""
from __future__ import annotations

from pathlib import Path

from app import store
from app import pipeline
from app.pipeline import ROOT, is_mock

IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp")


def file_url(path: str | None) -> str | None:
    if not path:
        return None
    p = Path(path)
    if p.is_absolute():
        try:
            path = str(p.resolve().relative_to(ROOT.resolve()))
        except ValueError:
            return None  # outside the repo: /files/ will not serve it
    return "/files/" + str(path).lstrip("/")


def latest_twin() -> dict | None:
    return store.latest()


def latest_snapshot() -> dict | None:
    """The latest analysed snapshot as a small object (None before the first twin)."""
    twin = store.latest()
    if twin is None:
        return None
    img = twin.get("image", {})
    return {
        "snapshot_id": twin.get("snapshot_id"), "page_id": twin.get("page_id"), "captured_at": twin.get("captured_at"),
        "source": twin.get("source"), "path": img.get("original_path"), "dewarped_path": img.get("dewarped_path"),
        "width": img.get("width"), "height": img.get("height"), "image_url": file_url(img.get("original_path")),
        "dewarped_url": file_url(img.get("dewarped_path")), "quality": twin.get("quality"),
        "line_count": len(twin.get("lines", [])), "mock": bool(twin.get("_fallback")) or is_mock(),
    }


def latest_frame_path() -> str | None:
    """Newest still in runtime/snapshots/ (repo-relative), analysed or not; None if there is none."""
    snapshot_dir = pipeline.SNAPSHOT_DIR  # read at call time (tests and embedders may repoint it)
    if not snapshot_dir.exists():
        return None
    files = [p for p in snapshot_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS]
    if not files:
        return None
    newest = max(files, key=lambda p: p.stat().st_mtime)
    try:
        return str(newest.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(newest)
