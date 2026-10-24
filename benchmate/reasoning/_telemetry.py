"""Telemetry shim. Uses app.telemetry.log when T5 has shipped it, else a no-op.

TODO(T5): remove the fallback once app/telemetry.py exists everywhere.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

try:  # pragma: no cover - depends on T5's progress
    from app.telemetry import log as _app_log  # type: ignore
except Exception:  # ImportError or a half-written module
    _app_log = None


def log(stage: str, ms: float, **extra: Any) -> None:
    """Forward to app.telemetry.log if available; never raise."""
    if _app_log is None:
        return
    try:
        _app_log(stage, ms, **extra)
    except Exception:
        pass


@contextmanager
def timed(stage: str, sink: dict[str, float] | None = None, **extra: Any) -> Iterator[None]:
    """Time a block, log it, and optionally record ms into `sink[stage]`."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        ms = (time.perf_counter() - t0) * 1000.0
        if sink is not None:
            sink[stage] = round(ms, 2)
        log(stage, ms, **extra)


def now_ms() -> Callable[[], float]:
    """Return a closure that yields elapsed ms since creation."""
    t0 = time.perf_counter()
    return lambda: (time.perf_counter() - t0) * 1000.0
