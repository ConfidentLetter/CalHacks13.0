"""Per-stage timing log.

    from app.telemetry import log, timed
    log("layout.segment", 412.0, lines=7)
    with timed("transcribe.page"):
        ...

Each call appends one JSON object `{ts, stage, ms, ...extra}` to
runtime/telemetry.jsonl. Appends are serialised with a lock, so it is safe
from threads and from the server's background tasks. Never raises: a logging
failure must not take down the pipeline.
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

ROOT = Path(__file__).resolve().parent.parent
TELEMETRY_PATH = Path(os.environ.get("SV_TELEMETRY", ROOT / "runtime" / "telemetry.jsonl"))

_lock = threading.Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="milliseconds")


def log(stage: str, ms: float, **extra: Any) -> None:
    """Append {ts, stage, ms, ...extra} to runtime/telemetry.jsonl."""
    record = {"ts": _now_iso(), "stage": stage, "ms": round(float(ms), 3), **extra}
    try:
        line = json.dumps(record, default=str)
    except (TypeError, ValueError):
        line = json.dumps({"ts": record["ts"], "stage": stage, "ms": record["ms"]})
    with _lock:
        try:
            TELEMETRY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with TELEMETRY_PATH.open("a", encoding="utf-8") as fh:
                fh.write(line + "\n")
        except OSError:
            pass


@contextmanager
def timed(stage: str, **extra: Any) -> Iterator[dict]:
    """Context manager that logs the elapsed wall time of its block.

    Yields a dict; anything the block puts in it is logged as extra fields,
    so callers can attach counts (`t["lines"] = 7`). An exception inside the
    block is logged with `error=<repr>` and re-raised.
    """
    fields: dict[str, Any] = {}
    start = time.perf_counter()
    try:
        yield fields
    except BaseException as exc:  # noqa: BLE001 - we re-raise
        fields.setdefault("error", f"{type(exc).__name__}: {exc}")
        raise
    finally:
        ms = (time.perf_counter() - start) * 1000.0
        log(stage, ms, **extra, **fields)


def read(limit: int | None = None, stage: str | None = None) -> list[dict]:
    """Read records back (most recent last). Skips malformed lines."""
    try:
        lines = TELEMETRY_PATH.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out: list[dict] = []
    for raw in lines:
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if stage is None or rec.get("stage") == stage:
            out.append(rec)
    return out[-limit:] if limit else out
