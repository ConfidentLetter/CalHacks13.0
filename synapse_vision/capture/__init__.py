"""T1 Capture: snapshots, stability trigger, page detection, dewarp, quality gate, tiling.

Submodules load lazily so `python -m capture.source` does not re-import itself.
"""
from __future__ import annotations

__all__ = ["get_snapshot", "wait_for_stable", "detect_and_dewarp", "tile"]

_EXPORTS = {"get_snapshot": "capture.source", "wait_for_stable": "capture.source",
            "detect_and_dewarp": "capture.page", "tile": "capture.page"}


def __getattr__(name: str):
    if name in _EXPORTS:
        import importlib

        return getattr(importlib.import_module(_EXPORTS[name]), name)
    raise AttributeError(f"module 'capture' has no attribute {name!r}")
