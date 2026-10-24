"""WebSocket fan-out for /events, plus the message shapes the Tutor team receives."""
from __future__ import annotations

import asyncio
import json
from typing import Any

from fastapi import WebSocket


class Hub:
    """Holds connected /events sockets and broadcasts JSON messages to all of them."""

    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self.recent: list[dict] = []  # last few status messages, for the viewer's dev drawer

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        async with self._lock:
            self._clients.add(ws)

    async def disconnect(self, ws: WebSocket) -> None:
        async with self._lock:
            self._clients.discard(ws)

    @property
    def count(self) -> int:
        return len(self._clients)

    async def broadcast(self, message: dict[str, Any]) -> None:
        if message.get("type") == "status":
            self.recent = (self.recent + [message])[-200:]
        payload = json.dumps(message, ensure_ascii=False, default=str)
        async with self._lock:
            clients = list(self._clients)
        dead: list[WebSocket] = []
        for ws in clients:
            try:
                await ws.send_text(payload)
            except Exception:  # noqa: BLE001 - a dead socket must not stop the others
                dead.append(ws)
        if dead:
            async with self._lock:
                for ws in dead:
                    self._clients.discard(ws)


def twin_messages(twin: dict) -> list[dict]:
    """The `/events` sequence for one twin: the twin, then one event per changed line."""
    by_id = {line["id"]: line for line in twin.get("lines", [])}
    changes = twin.get("changes", {})
    out: list[dict] = [{"type": "twin", "twin": twin}]
    for key, kind in (("added", "line_added"), ("edited", "line_edited"), ("crossed_out", "line_crossed_out")):
        for lid in changes.get(key, []):
            if lid in by_id:
                out.append({"type": kind, "snapshot_id": twin.get("snapshot_id"), "line": by_id[lid]})
    for lid in changes.get("removed", []):
        out.append({"type": "line_removed", "snapshot_id": twin.get("snapshot_id"), "line_id": lid})
    return out


def status(stage: str, **fields: Any) -> dict:
    return {"type": "status", "stage": stage, **fields}
