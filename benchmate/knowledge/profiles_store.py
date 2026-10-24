"""Component profiles: knowledge/profiles/<part_id>.yaml (schema: contracts/profile.example.yaml).

Profiles are cached by file mtime so list_profiles() is cheap to call on every request.
"""
from __future__ import annotations

import copy
import threading
from pathlib import Path

import yaml

from ._telemetry import log
from .paths import PROFILES_DIR
from .validation import is_valid_part_id

_REQUIRED_KEYS = ("part_id", "role", "aliases", "footprint")
_lock = threading.Lock()
_cache: dict[Path, tuple[int, dict]] = {}   # path -> (mtime_ns, profile)


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: profile must be a YAML mapping")
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"{path}: profile missing keys {missing}")
    return data


def _cached(path: Path) -> dict:
    mtime = path.stat().st_mtime_ns
    with _lock:
        hit = _cache.get(path)
        if hit and hit[0] == mtime:
            return hit[1]
    data = _load_yaml(path)
    with _lock:
        _cache[path] = (mtime, data)
    return data


def _profile_path(part_id: str) -> Path:
    if not is_valid_part_id(part_id):
        raise KeyError(part_id)
    return PROFILES_DIR / f"{part_id}.yaml"


def get_profile(part_id: str) -> dict:
    """Parsed knowledge/profiles/<part_id>.yaml. KeyError if missing."""
    path = _profile_path(part_id)
    if not path.is_file():
        raise KeyError(part_id)
    return copy.deepcopy(_cached(path))


def list_profiles() -> list[dict]:
    """All valid profiles, sorted by part_id (T2 uses `aliases` for normalization). A malformed file is
    skipped and logged rather than taking every caller down with it."""
    out = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        try:
            out.append(copy.deepcopy(_cached(path)))
        except Exception as exc:
            log("knowledge.profile_invalid", 0.0, file=path.name, error=str(exc)[:160])
    return out
