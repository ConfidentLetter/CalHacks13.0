"""Label helper: a local page at /label for correcting pre-labels (served by app/server.py).

Routes (all local, no auth — it is a tool for Henry on his laptop):
    GET  /label                          the page (eval/label.html)
    GET  /label/api/pages                [{name, has_truth, reviewed, lines, planted}]
    GET  /label/api/page/{name}          {truth, image_url, dewarped_url}
    POST /label/api/page/{name}          save the truth JSON from the page
    POST /label/api/page/{name}/prelabel re-run pre-labelling (query: force=1, mock=1)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse

from eval import prelabel
from eval import truth as T

HTML_PATH = Path(__file__).resolve().parent / "label.html"
router = APIRouter()


def _file_url(p: str | None) -> str | None:
    return f"/files/{str(p).lstrip('/')}" if p else None


def _summary(name: str) -> dict:
    truth = T.load_truth(name)
    lines = truth.get("lines", []) if truth else []
    return {"name": name, "has_truth": truth is not None, "reviewed": bool(truth and truth.get("reviewed")),
            "lines": len(lines), "planted": sum(1 for l in lines if l.get("planted_error"))}


@router.get("/label", response_class=HTMLResponse)
async def label_page():
    if not HTML_PATH.exists():
        return HTMLResponse("<p>eval/label.html missing</p>", status_code=500)
    return HTMLResponse(HTML_PATH.read_text(encoding="utf-8"))


@router.get("/label/api/pages")
async def label_pages():
    return {"pages": [_summary(n) for n in T.page_names()], "testset": str(T.TESTSET_DIR)}


@router.get("/label/api/page/{name}")
async def label_get(name: str):
    try:
        truth = T.load_truth(name)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, 400)
    image = T.image_path(name)
    if image is None:
        return JSONResponse({"error": f"no photo named {name} in {T.TESTSET_DIR}"}, 404)
    rel = T.rel(image)
    dewarped = truth.get("dewarped_path") if truth else None
    if dewarped and not (T.ROOT / dewarped).exists():
        dewarped = None  # e.g. the mock twin's placeholder path; the page falls back to the original photo
    return {"name": name, "truth": truth, "image_url": _file_url(rel), "dewarped_url": _file_url(dewarped)}


@router.post("/label/api/page/{name}")
async def label_save(name: str, request: Request):
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        return JSONResponse({"error": "body must be JSON"}, 400)
    truth = body.get("truth", body) if isinstance(body, dict) else None
    errors = T.validate_truth(truth)
    if errors:
        return JSONResponse({"error": "invalid truth", "details": errors}, 422)
    try:
        path = T.save_truth(name, truth)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, 400)
    return {"saved": T.rel(path), "summary": _summary(name)}


@router.post("/label/api/page/{name}/prelabel")
async def label_prelabel(name: str, force: int = 0, mock: int = 0):
    try:
        out = await asyncio.to_thread(prelabel.prelabel_page, name, bool(force), bool(mock))
    except Exception as exc:  # noqa: BLE001 - model/pipeline failures are reported, not fatal
        return JSONResponse({"error": f"{type(exc).__name__}: {exc}"}, 500)
    if out is None:
        return JSONResponse({"error": "skipped: no photo, or truth exists and is reviewed / force=0"}, 409)
    return {"wrote": T.rel(out), "summary": _summary(name)}
