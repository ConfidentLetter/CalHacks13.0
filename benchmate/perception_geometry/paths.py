"""Runtime output locations. Honours env BM_RUNTIME_DIR (T5's convention; tests point it at a tmp dir)."""
from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def runtime_dir() -> Path:
    return Path(os.environ.get("BM_RUNTIME_DIR", REPO_ROOT / "runtime"))


def tiles_dir() -> Path:
    d = runtime_dir() / "tiles"
    d.mkdir(parents=True, exist_ok=True)
    return d


def debug_dir() -> Path:
    d = runtime_dir() / "debug"
    d.mkdir(parents=True, exist_ok=True)
    return d
