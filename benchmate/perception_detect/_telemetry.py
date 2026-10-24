"""Telemetry shim: use app.telemetry.log when T5 ships it, else a no-op.

TODO(T5): once app/telemetry.py exists, this resolves to the real logger automatically.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

try:  # pragma: no cover - depends on T5's progress
    from app.telemetry import log  # type: ignore
except Exception:  # ImportError or a half-written module

    def log(stage: str, ms: float, **extra) -> None:  # type: ignore[misc]
        """No-op until app/telemetry.py exists."""
        return None


@contextmanager
def timed(stage: str, **extra) -> Iterator[dict]:
    """Context manager that logs the elapsed ms of a stage.

    Usage: with timed("detect_components", tiles=3) as t: ...; t["ms"] is set afterwards.
    """
    info: dict = {}
    start = time.perf_counter()
    try:
        yield info
    finally:
        ms = (time.perf_counter() - start) * 1000.0
        info["ms"] = ms
        try:
            log(stage, ms, **{**extra, **{k: v for k, v in info.items() if k != "ms"}})
        except Exception:
            pass
