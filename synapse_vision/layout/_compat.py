"""Config and telemetry access with local no-op fallbacks.

T4 owns ``app/config.py`` and ``app/telemetry.py``.  Until they exist we read
``config/vision.yaml`` directly and swallow telemetry.
TODO(T2): drop the YAML fallback once app.config is stable.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = REPO_ROOT / "config" / "vision.yaml"


def _yaml_get(key: str, default: Any = None) -> Any:
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(_CONFIG_PATH.read_text()) or {}
    except Exception:  # noqa: BLE001 - config missing or unreadable -> defaults
        return default
    node: Any = data
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def config_get(key: str, default: Any = None) -> Any:
    """Dotted lookup into config/vision.yaml via app.config when available."""
    try:
        from app.config import get as _app_get  # type: ignore

        value = _app_get(key, default)
        return default if value is None else value
    except Exception:  # noqa: BLE001 - T4 module missing or half-written
        value = _yaml_get(key, default)
        return default if value is None else value


def telemetry_log(stage: str, ms: float, **extra: Any) -> None:
    try:
        from app.telemetry import log as _app_log  # type: ignore
    except Exception:  # noqa: BLE001
        return
    try:
        _app_log(stage, ms, **extra)
    except Exception:  # noqa: BLE001 - never let telemetry break the pipeline
        return


@contextmanager
def timed(stage: str, **extra: Any) -> Iterator[dict]:
    """``with timed("layout.segment", n_lines=...) as t:`` -> logs elapsed ms on exit.

    Callers may add fields to the yielded dict; they are forwarded to telemetry.
    """
    info: dict = dict(extra)
    t0 = time.perf_counter()
    try:
        yield info
    finally:
        telemetry_log(stage, (time.perf_counter() - t0) * 1000.0, **info)
