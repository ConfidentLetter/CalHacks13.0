"""Small deterministic id / timestamp helpers."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_snapshot_id() -> str:
    return "snap_" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:6]


def new_page_id() -> str:
    return "page_" + uuid.uuid4().hex[:8]


def next_line_id(existing: set[str]) -> str:
    """Next free 'L<n>' not in `existing`."""
    used = set()
    for lid in existing:
        if lid.startswith("L") and lid[1:].isdigit():
            used.add(int(lid[1:]))
    n = 0
    while n in used:
        n += 1
    return f"L{n}"
