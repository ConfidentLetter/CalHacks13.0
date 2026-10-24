"""Synapse Vision + team-frontend bridge: ONE process on port 8000.

    uvicorn bridge.server:app --host 0.0.0.0 --port 8000
    SV_MOCK=1 uvicorn bridge.server:app --port 8000     # mock twin, no camera, no model for the vision part

T4's `app.server.app` is imported (never forked) and extended with the `/api/*` router and CORS for the
dashboard origin. Every T4 route (/twin/*, /snapshot, /upload, WS /events, /files/*, viewer) keeps working.
Request-body size: Starlette/uvicorn impose no JSON body limit, so the contract's ≥ 3 MB stills pass as-is
(bridge/tests/test_server.py proves it); a reverse proxy in front must raise its own limit.
"""
from __future__ import annotations

import os

from fastapi.middleware.cors import CORSMiddleware

from app.server import app as vision_app
from bridge.api import router as bridge_router

DEFAULT_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")


def allowed_origins() -> list[str]:
    """Dashboard origins; extend with SV_CORS_ORIGINS="http://10.0.6.238:5173,..." at the venue."""
    extra = [o.strip() for o in os.environ.get("SV_CORS_ORIGINS", "").split(",") if o.strip()]
    return [*DEFAULT_ORIGINS, *extra]


def _extend(app) -> None:
    if getattr(app.state, "bridge_installed", False):
        return
    # Starlette refuses add_middleware once the stack is built (e.g. T4's tests ran first in the same process);
    # resetting the lazily-built stack is safe: it is rebuilt on the next request.
    app.middleware_stack = None
    app.include_router(bridge_router)
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins(), allow_methods=["*"], allow_headers=["*"],
                       allow_credentials=False, max_age=600)
    app.state.bridge_installed = True


_extend(vision_app)
app = vision_app


def main() -> None:
    import argparse

    import uvicorn

    p = argparse.ArgumentParser(description="Synapse Vision bridge server (T4 routes + /api/* for the frontend)")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--mock", action="store_true", help="same as SV_MOCK=1")
    a = p.parse_args()
    if a.mock:
        os.environ["SV_MOCK"] = "1"
    uvicorn.run("bridge.server:app", host=a.host, port=a.port, log_level="info")


if __name__ == "__main__":
    main()
