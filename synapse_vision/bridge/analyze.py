"""POST /api/camera/analyze orchestration: still → runtime/uploads → T4's analyze() (real T1→T2→T3 chain) → judge."""
from __future__ import annotations

import asyncio
import time
from typing import Any

from bridge import images, tutor
from bridge.compat import cfg, file_url, log, now_iso

DEFAULT_PIPELINE_TIMEOUT_S = 45.0
DEFAULT_TOTAL_BUDGET_S = 58.0  # the UI gives up at 60 s


class ResolveError(ValueError):
    """The request's `image` could not be turned into a file on disk."""


def resolve_image(image: Any) -> dict:
    """`image.base64` or `image.snapshotId` → {id, path, source, capturedAt}. Raises ResolveError."""
    if not isinstance(image, dict):
        raise ResolveError("body needs an 'image' object (base64 still or snapshotId)")
    captured_at = image.get("capturedAt")
    if image.get("base64"):
        try:
            data, ext = images.decode_base64_image(str(image["base64"]))
        except images.ImageError as exc:
            raise ResolveError(str(exc)) from exc
        still_id, path = images.save_still(data, ext)
        source = "webcam" if image.get("source") != "hardware" else "pi"
        images.register_still(still_id, path, source, captured_at)
        return {"id": still_id, "path": path, "source": source, "capturedAt": captured_at or now_iso()}
    snapshot_id = str(image.get("snapshotId") or "").strip()
    if snapshot_id:
        entry = images.lookup_still(snapshot_id)
        if entry:
            return {"id": snapshot_id, "path": entry["path"], "source": entry["source"], "capturedAt": entry["capturedAt"]}
        twin = _stored_twin(snapshot_id)
        if twin:
            return {"id": snapshot_id, "path": twin["image"]["original_path"], "source": twin.get("source") or "webcam",
                    "capturedAt": twin.get("captured_at"), "twin": twin}
        raise ResolveError(f"unknown snapshotId {snapshot_id!r}; take a new still with POST /api/camera/capture")
    raise ResolveError("image needs either 'base64' or 'snapshotId'")


def _stored_twin(snapshot_id: str) -> dict | None:
    try:
        from app import store

        return store.get(snapshot_id)
    except Exception:  # noqa: BLE001
        return None


async def run_pipeline(path: str, source: str, timeout_s: float | None = None) -> tuple[dict | None, str | None]:
    """T4's analyze() (stores the twin, broadcasts on /events). Returns (twin, None) or (None, error)."""
    timeout = float(timeout_s or cfg("bridge.pipeline_timeout_s", DEFAULT_PIPELINE_TIMEOUT_S))
    t0 = time.perf_counter()
    try:
        from app import server as vision_server

        twin = await asyncio.wait_for(vision_server.analyze(path, source), timeout=timeout)
    except asyncio.TimeoutError:
        log("bridge.pipeline", (time.perf_counter() - t0) * 1000.0, error="timeout", timeout_s=timeout)
        return None, f"the vision pipeline took longer than {timeout:.0f} s"
    except Exception as exc:  # noqa: BLE001 - PipelineError or anything else: report, never 500
        log("bridge.pipeline", (time.perf_counter() - t0) * 1000.0, error=f"{type(exc).__name__}: {exc}")
        return None, f"{type(exc).__name__}: {exc}"
    log("bridge.pipeline", (time.perf_counter() - t0) * 1000.0, snapshot_id=twin.get("snapshot_id"),
        lines=len(twin.get("lines") or []))
    return twin, None


def _failed(still: dict, reason: str) -> dict:
    return {"snapshotId": still["id"], "analyzedAt": now_iso(), "summary": f"Analysis failed: {reason}.",
            "topics": [], "steps": [], "hints": [], "analysisFailed": True, "imageUrl": file_url(still.get("path"))}


async def analyze_request(body: Any, *, budget_s: float | None = None) -> dict:
    """The whole endpoint minus HTTP. Raises ResolveError for bad input; everything else becomes a 200 body."""
    if not isinstance(body, dict):
        raise ResolveError("body must be a JSON object")
    t0 = time.perf_counter()
    budget = float(budget_s or cfg("bridge.analyze_budget_s", DEFAULT_TOTAL_BUDGET_S))
    still = await asyncio.to_thread(resolve_image, body.get("image"))
    twin = still.get("twin")
    if twin is None:
        twin, error = await run_pipeline(still["path"], still["source"],
                                         min(float(cfg("bridge.pipeline_timeout_s", DEFAULT_PIPELINE_TIMEOUT_S)), budget - 8))
        if twin is None:
            return _failed(still, error or "unknown error")
    remaining = max(5.0, budget - (time.perf_counter() - t0))
    try:
        judged = await asyncio.wait_for(asyncio.to_thread(tutor.judge_twin, twin), timeout=remaining)
    except asyncio.TimeoutError:
        judged = {"summary": "Analysis timed out while judging; the lines are shown as transcribed, unjudged.",
                  "topics": [], "hints": [], "analysisFailed": True,
                  "steps": [{"id": l["id"], "label": tutor.label_of(l), "status": "unclear", "note": "",
                             "confidence": l["confidence"], "lineStatus": l["status"]} for l in tutor.twin_lines(twin)]}
    except Exception as exc:  # noqa: BLE001
        judged = {"summary": f"Analysis failed while judging ({type(exc).__name__}: {exc}).", "topics": [], "hints": [],
                  "analysisFailed": True, "steps": []}
    image = twin.get("image") or {}
    out = {
        "snapshotId": twin.get("snapshot_id") or still["id"], "stillId": still["id"], "analyzedAt": now_iso(),
        **{k: judged.get(k, v) for k, v in (("summary", ""), ("topics", []), ("steps", []), ("hints", []))},
        "imageUrl": file_url(image.get("original_path") or still.get("path")),
        "dewarpedUrl": file_url(image.get("dewarped_path")),
        "quality": twin.get("quality"), "lineCount": len(twin.get("lines") or []),
        "latencyMs": {**(twin.get("latency_ms") or {}), "bridge_total": round((time.perf_counter() - t0) * 1000.0, 1)},
    }
    if judged.get("analysisFailed"):
        out["analysisFailed"] = True
    if twin.get("_fallback"):
        out["fallback"] = twin["_fallback"]
    log("bridge.analyze", out["latencyMs"]["bridge_total"], snapshot_id=out["snapshotId"], steps=len(out["steps"]),
        errors=sum(1 for s in out["steps"] if s.get("status") == "error"))
    return out
