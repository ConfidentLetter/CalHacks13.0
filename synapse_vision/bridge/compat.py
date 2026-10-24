"""Shared helpers for the bridge: config/telemetry pass-throughs, ids, timestamps, repo paths."""
from __future__ import annotations

import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = REPO_ROOT / "runtime"


def cfg(key: str, default: Any = None) -> Any:
    """`app.config.get` when available (always, since T4 shipped), else the default."""
    try:
        from app.config import get as app_get
    except Exception:  # noqa: BLE001 - T4 module missing or half-written
        return default
    try:
        value = app_get(key, default)
    except Exception:  # noqa: BLE001
        return default
    return default if value is None else value


def log(stage: str, ms: float, **extra: Any) -> None:
    """`app.telemetry.log` when available; never raises."""
    try:
        from app.telemetry import log as app_log
    except Exception:  # noqa: BLE001
        return
    try:
        app_log(stage, ms, **extra)
    except Exception:  # noqa: BLE001
        return


@contextmanager
def timed(stage: str, **extra: Any) -> Iterator[dict]:
    """`with timed("bridge.analyze") as t: t["lines"] = 4` → one telemetry record on exit."""
    fields: dict[str, Any] = {}
    t0 = time.perf_counter()
    try:
        yield fields
    except BaseException as exc:  # noqa: BLE001 - re-raised below
        fields.setdefault("error", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        log(stage, (time.perf_counter() - t0) * 1000.0, **extra, **fields)


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"


def repo_relative(path: str | Path) -> str:
    """Repo-relative string when the path is inside the repo (so /files/ can serve it), else absolute."""
    p = Path(path)
    if not p.is_absolute():
        p = REPO_ROOT / p
    try:
        return str(p.resolve().relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(p.resolve())


def file_url(path: str | None) -> str | None:
    """The `/files/...` URL T4 serves for a repo-relative path; None if outside the repo or empty."""
    if not path:
        return None
    rel = repo_relative(path)
    if Path(rel).is_absolute():
        return None
    return "/files/" + rel.replace("\\", "/")


def error_body(message: str) -> dict:
    """The frontend contract's error shape."""
    return {"error": message}
