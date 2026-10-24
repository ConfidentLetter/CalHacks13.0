"""build_page_twin: T1 detect_and_dewarp -> T2 segment -> transcribe_page -> temporal matching -> validated twin."""
from __future__ import annotations

import os
import time
from pathlib import Path

from transcribe.compat import REPO_ROOT, Timer, cfg, log
from transcribe.ids import new_snapshot_id, now_iso
from transcribe.ink import resolve
from transcribe.matching import match_to_previous
from transcribe.page import transcribe_page
from transcribe.schema import load_mock_twin, validate_twin

IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def mock_twin(snapshot_path: str = "", source: str = "mock") -> dict:
    """The committed mock twin, re-stamped. Demo backup (SV_MOCK=1) and T4's fallback."""
    twin = load_mock_twin()
    image = {**twin["image"], "original_path": snapshot_path or twin["image"]["original_path"]}
    return validate_twin({**twin, "snapshot_id": new_snapshot_id(), "captured_at": now_iso(),
                          "source": source, "image": image})


def _source_for(snapshot_path: str) -> str:
    name = Path(snapshot_path).name.lower()
    if name.startswith("upload") or name.startswith("mock"):
        return "upload" if name.startswith("upload") else "mock"
    env = os.environ.get("SV_SOURCE", str(cfg("capture.source", "upload"))).split(":")[0]
    return env if env in ("pi", "webcam", "upload", "mock") else "upload"


def _image_size(path: str) -> tuple[int, int]:
    import cv2

    img = cv2.imread(str(resolve(path)), cv2.IMREAD_COLOR)
    return (0, 0) if img is None else (int(img.shape[1]), int(img.shape[0]))


def _detect(snapshot_path: str) -> dict:
    """T1 detect_and_dewarp; if missing/raising, use the photo as-is with quality.ok=False."""
    try:
        from capture.page import detect_and_dewarp

        page = detect_and_dewarp(snapshot_path)
        page.setdefault("quality", {})
        page["quality"].setdefault("ok", False)
        page["quality"].setdefault("issues", [])
        return page
    except Exception as exc:  # noqa: BLE001
        log("transcribe.detect_fallback", 0.0, error=f"{type(exc).__name__}: {exc}")
        w, h = _image_size(snapshot_path)
        return {"dewarped_path": snapshot_path, "width": w, "height": h, "homography": IDENTITY,
                "quality": {"ok": w > 0, "issues": [] if w > 0 else ["no_page"], "blur_score": 0.0, "glare_fraction": 0.0}}


def _segment(dewarped_path: str) -> dict:
    """T2 segment; if missing/raising, an empty layout (no lines, no hallucinated boxes)."""
    try:
        from layout import segment

        return segment(dewarped_path)
    except Exception as exc:  # noqa: BLE001
        log("transcribe.segment_fallback", 0.0, error=f"{type(exc).__name__}: {exc}")
        return {"regions": [], "lines": []}


def _rel(path: str) -> str:
    p = Path(path)
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p)


def build_page_twin(snapshot_path: str, previous_twin: dict | None = None) -> dict:
    """Full pipeline: T1 detect_and_dewarp -> T2 segment -> transcribe_page -> match lines to previous_twin
    (stable ids, changes.added/edited/removed/crossed_out, first_seen/last_changed) -> validate against page_twin.schema.json."""
    t0 = time.perf_counter()
    latency: dict[str, float] = {}
    with Timer("transcribe.build.page") as t:
        page = _detect(snapshot_path)
    latency["page"] = round(t.ms, 1)
    quality = page["quality"]
    with Timer("transcribe.build.layout") as t:
        layout = _segment(page["dewarped_path"])
    latency["layout"] = round(t.ms, 1)
    with Timer("transcribe.build.transcribe") as t:
        lines = transcribe_page(page["dewarped_path"], {**layout, "quality": quality}, previous_twin)
    latency["transcribe"] = round(t.ms, 1)
    now = now_iso()
    matched = match_to_previous(lines, previous_twin, now, quality_ok=bool(quality.get("ok")))
    regions = [{"id": str(r["id"]), "type": r.get("type", "work"), "bbox": [float(v) for v in r["bbox"]]}
               for r in layout.get("regions") or []]
    width, height = int(page.get("width") or 0), int(page.get("height") or 0)
    if width == 0 or height == 0:
        width, height = _image_size(page["dewarped_path"])
    latency["total"] = round((time.perf_counter() - t0) * 1000.0, 1)
    latency["snapshot_to_twin"] = latency["total"]
    twin = {
        "page_id": matched.page_id,
        "snapshot_id": new_snapshot_id(),
        "captured_at": now,
        "source": _source_for(snapshot_path),
        "image": {"original_path": _rel(snapshot_path), "dewarped_path": _rel(page["dewarped_path"]),
                  "width": width, "height": height, "homography": page.get("homography") or IDENTITY},
        "quality": {"ok": bool(quality.get("ok")), "issues": list(quality.get("issues") or []),
                    "blur_score": float(quality.get("blur_score") or 0.0),
                    "glare_fraction": float(quality.get("glare_fraction") or 0.0)},
        "regions": regions,
        "lines": matched.lines,
        "changes": matched.changes,
        "latency_ms": latency,
    }
    log("transcribe.build", latency["total"], lines=len(twin["lines"]), added=len(matched.changes["added"]),
        edited=len(matched.changes["edited"]), quality_ok=twin["quality"]["ok"])
    return validate_twin(twin)
