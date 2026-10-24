"""Hot-reloaded access to config/vision.yaml.

    from app.config import get
    get("transcribe.low_confidence", 0.6)

The file is re-read whenever its mtime changes, so Henry can tune thresholds
while the server runs. Never raises on a missing key: returns `default`.
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = Path(os.environ.get("SV_CONFIG", ROOT / "config" / "vision.yaml"))

_lock = threading.Lock()
_cache: dict[str, Any] = {"mtime": None, "data": {}}


def _load() -> dict:
    """Return the parsed config, re-reading the file if its mtime changed."""
    try:
        mtime = CONFIG_PATH.stat().st_mtime
    except OSError:
        return {}
    with _lock:
        if _cache["mtime"] != mtime:
            try:
                data = yaml.safe_load(CONFIG_PATH.read_text()) or {}
            except (OSError, yaml.YAMLError):
                # Half-written file during an edit: keep the last good copy.
                return dict(_cache["data"])
            _cache["mtime"] = mtime
            _cache["data"] = data if isinstance(data, dict) else {}
        return dict(_cache["data"])


def get(key: str, default: Any = None) -> Any:
    """Dotted lookup ("section.key") into config/vision.yaml. Returns `default` if absent."""
    node: Any = _load()
    for part in key.split("."):
        if not isinstance(node, dict) or part not in node:
            return default
        node = node[part]
    return node


def all() -> dict:  # noqa: A001 - mirrors the shape callers expect
    """The whole config as a dict (a copy)."""
    return _load()


def path() -> Path:
    """Where the config is being read from."""
    return CONFIG_PATH
