"""Component profiles: knowledge/profiles/<part_id>.yaml (schema: contracts/profile.example.yaml)."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

from .paths import PROFILES_DIR

_REQUIRED_KEYS = ("part_id", "role", "aliases", "footprint")


def _load_yaml(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: profile must be a YAML mapping")
    missing = [k for k in _REQUIRED_KEYS if k not in data]
    if missing:
        raise ValueError(f"{path}: profile missing keys {missing}")
    return data


def _profile_path(part_id: str) -> Path:
    if not part_id or "/" in part_id or part_id.startswith("."):
        raise KeyError(part_id)
    return PROFILES_DIR / f"{part_id}.yaml"


def get_profile(part_id: str) -> dict:
    """Parsed knowledge/profiles/<part_id>.yaml. KeyError if missing."""
    path = _profile_path(part_id)
    if not path.is_file():
        raise KeyError(part_id)
    return copy.deepcopy(_load_yaml(path))


def list_profiles() -> list[dict]:
    """All profiles, sorted by part_id (T2 uses `aliases` for normalization)."""
    out = []
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        out.append(_load_yaml(path))
    return out
