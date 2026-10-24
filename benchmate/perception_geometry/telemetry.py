"""Telemetry shim: use app.telemetry.log when T5 has shipped it, otherwise a no-op.

Resolved lazily on every call so the real logger is picked up as soon as app/telemetry.py
appears, without restarting the process. TODO(T5): remove the fallback once app/telemetry.py is stable.
"""
from __future__ import annotations

import functools
import time
from typing import Callable

_real_log: Callable | None = None
_checked_at = 0.0
_RECHECK_S = 5.0


def log(stage: str, ms: float, **extra) -> None:
    global _real_log, _checked_at
    if _real_log is None and time.monotonic() - _checked_at > _RECHECK_S:
        _checked_at = time.monotonic()
        try:
            from app.telemetry import log as real  # type: ignore
            _real_log = real
        except Exception:  # ImportError, or T5's module is half-written
            _real_log = None
    if _real_log is not None:
        try:
            _real_log(stage, ms, **extra)
        except Exception:
            pass  # telemetry must never break the pipeline


def timed(stage: str):
    """Decorator: log wall time of the call under `stage`."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                log(stage, (time.perf_counter() - t0) * 1000.0)
        return wrapper
    return deco
