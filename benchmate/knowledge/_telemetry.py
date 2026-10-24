"""Telemetry shim: use app.telemetry.log when T5 has shipped it, otherwise a no-op.

TODO(T4): remove the fallback once app/telemetry.py is guaranteed to exist.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from typing import Iterator

try:  # pragma: no cover - depends on T5's progress
    from app.telemetry import log  # type: ignore
except Exception:  # ImportError or a half-written module
    def log(stage: str, ms: float, **extra) -> None:  # noqa: D401 - no-op stub
        """No-op until app/telemetry.py exists."""
        return None


@contextmanager
def timed(stage: str, **extra) -> Iterator[None]:
    """Time a block and log it as `stage` (prefixed with knowledge.)."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        log(f"knowledge.{stage}", (time.perf_counter() - t0) * 1000.0, **extra)
