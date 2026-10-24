"""Fallbacks for T4's app.config / app.telemetry so transcribe/ works before they exist.

TODO(T3): once app/config.py and app/telemetry.py land, these shims become pass-throughs.
"""
from __future__ import annotations

import time
from functools import lru_cache
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "vision.yaml"


@lru_cache(maxsize=1)
def _load_yaml_cached(mtime: float) -> dict:
    import yaml

    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _local_get(key: str, default: Any = None) -> Any:
    """Dotted lookup into config/vision.yaml, re-read whenever the file changes."""
    try:
        data = _load_yaml_cached(CONFIG_PATH.stat().st_mtime)
    except (OSError, ValueError):
        return default
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def cfg(key: str, default: Any = None) -> Any:
    """Read a tunable via app.config.get when available, else from vision.yaml directly."""
    try:
        from app.config import get as app_get  # type: ignore
    except Exception:  # noqa: BLE001 - T4 module may be missing or half-written
        return _local_get(key, default)
    try:
        value = app_get(key, default)
    except Exception:  # noqa: BLE001
        return _local_get(key, default)
    return default if value is None else value


def log(stage: str, ms: float, **extra: Any) -> None:
    """Forward to app.telemetry.log when available; otherwise a no-op."""
    try:
        from app.telemetry import log as app_log  # type: ignore
    except Exception:  # noqa: BLE001
        return
    try:
        app_log(stage, ms, **extra)
    except Exception:  # noqa: BLE001
        return


class Timer:
    """`with Timer("stage") as t:` logs elapsed ms on exit and exposes t.ms."""

    def __init__(self, stage: str, **extra: Any) -> None:
        self.stage = stage
        self.extra = extra
        self.ms = 0.0
        self._t0 = 0.0

    def __enter__(self) -> "Timer":
        self._t0 = time.perf_counter()
        return self

    def __exit__(self, *_: Any) -> None:
        self.ms = (time.perf_counter() - self._t0) * 1000.0
        log(self.stage, self.ms, **self.extra)
