"""Fallbacks for T4's ``app.config.get`` / ``app.telemetry.log`` so capture/ works before they exist.

TODO(T1): once app/config.py and app/telemetry.py land, cfg()/log() become pass-throughs automatically.
"""
from __future__ import annotations

import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "config" / "vision.yaml"
RUNTIME_DIR = REPO_ROOT / "runtime"

_yaml_cache: dict[str, Any] = {"mtime": None, "data": {}}


def _load_yaml() -> dict:
    """Read config/vision.yaml, re-parsing only when the file's mtime changes."""
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    if _yaml_cache["mtime"] != mtime:
        import yaml

        with CONFIG_PATH.open("r", encoding="utf-8") as fh:
            _yaml_cache.update(mtime=mtime, data=yaml.safe_load(fh) or {})
    return _yaml_cache["data"]


def _local_get(key: str, default: Any = None) -> Any:
    node: Any = _load_yaml()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def cfg(key: str, default: Any = None) -> Any:
    """Tunable lookup: app.config.get if T4 has shipped it, else config/vision.yaml directly."""
    try:
        from app.config import get as _get  # type: ignore
    except Exception:
        return _local_get(key, default)
    try:
        value = _get(key, default)
    except Exception:
        return _local_get(key, default)
    return _local_get(key, default) if value is None else value


def log(stage: str, ms: float, **extra: Any) -> None:
    """Telemetry: app.telemetry.log if available, else a silent no-op."""
    try:
        from app.telemetry import log as _log  # type: ignore
    except Exception:
        return
    try:
        _log(stage, ms, **extra)
    except Exception:
        return


@contextmanager
def timed(stage: str, **extra: Any) -> Iterator[dict]:
    """``with timed("capture.page") as t:`` logs elapsed ms on exit; t['ms'] holds the value."""
    info: dict[str, Any] = {"ms": 0.0}
    t0 = time.perf_counter()
    try:
        yield info
    finally:
        info["ms"] = (time.perf_counter() - t0) * 1000.0
        log(stage, info["ms"], **extra)


def repo_relative(path: str | Path) -> str:
    """Repo-relative string when the file is inside the repo (T4's viewer serves those at /files/), else absolute."""
    resolved = Path(path).resolve()
    try:
        return str(resolved.relative_to(REPO_ROOT.resolve()))
    except ValueError:
        return str(resolved)


def absolute(path: str | Path) -> Path:
    """Inverse of repo_relative: resolve a repo-relative or absolute path to an absolute one."""
    p = Path(path)
    return p if p.is_absolute() else (REPO_ROOT / p)


def runtime_dir(sub: str) -> Path:
    path = RUNTIME_DIR / sub
    path.mkdir(parents=True, exist_ok=True)
    return path
