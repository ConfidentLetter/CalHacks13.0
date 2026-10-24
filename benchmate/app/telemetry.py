"""Telemetry: one JSON line per pipeline stage in runtime/telemetry.jsonl.

Every terminal imports this:

    from app.telemetry import log, timed

    log("twin", 1830.2, frame_id="f_001")
    with timed("rules", frame_id="f_001"):
        ...

Design: append-only, thread-safe (one process-wide lock), never raises into the
caller. Telemetry must never be the reason the demo crashes.
"""
from __future__ import annotations

import json
import os
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent

_LOCK = threading.Lock()
_listeners: list = []  # callables(record: dict) -> None; the server uses this to push "status" over WS


def runtime_dir() -> Path:
    """Where runtime artefacts go. Env BM_RUNTIME_DIR overrides (tests use a tmp dir)."""
    return Path(os.environ.get("BM_RUNTIME_DIR", REPO_ROOT / "runtime"))


def telemetry_path() -> Path:
    return runtime_dir() / "telemetry.jsonl"


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def _json_safe(value: Any) -> Any:
    """Coerce arbitrary extras to something json.dumps accepts (fall back to repr)."""
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def log(stage: str, ms: float, **extra) -> None:
    """Append {ts, stage, ms, **extra} to runtime/telemetry.jsonl. Never raises."""
    record = {"ts": _now_iso(), "stage": str(stage), "ms": round(float(ms), 3)}
    record.update({k: _json_safe(v) for k, v in extra.items()})
    line = json.dumps(record, ensure_ascii=False)
    try:
        path = telemetry_path()
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
    except OSError as exc:  # disk full, read-only dir, ... keep the pipeline alive
        print(f"[telemetry] could not write {stage}: {exc}")
    for cb in list(_listeners):
        try:
            cb(record)
        except Exception as exc:  # a bad listener must not break logging
            print(f"[telemetry] listener failed: {exc}")


@contextmanager
def timed(stage: str, **extra) -> Iterator[dict]:
    """Time a block and log it. Yields a dict you may add extras to inside the block.

    If the block raises, the record is still written with error=<ExceptionType: msg>
    and the exception propagates.
    """
    info: dict = dict(extra)
    t0 = time.perf_counter()
    try:
        yield info
    except Exception as exc:
        info.setdefault("error", f"{type(exc).__name__}: {exc}"[:200])
        raise
    finally:
        log(stage, (time.perf_counter() - t0) * 1000.0, **info)


def add_listener(callback) -> None:
    """Register callback(record) called after every log(). Used by app.server for WS status."""
    if callback not in _listeners:
        _listeners.append(callback)


def remove_listener(callback) -> None:
    if callback in _listeners:
        _listeners.remove(callback)


def read_recent(n: int = 200) -> list[dict]:
    """Last n records (oldest first). Tolerates a partially written last line."""
    path = telemetry_path()
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for line in reversed(lines):  # newest first, skip broken lines, stop at n good ones
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
        if len(out) >= n:
            break
    return out[::-1]
