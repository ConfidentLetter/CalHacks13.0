"""Component profiles. Prefers T4's knowledge module, then knowledge/profiles/*.yaml,
then the two example documents in contracts/profile.example.yaml."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from reasoning.config import ROOT

EXAMPLE_PROFILES = ROOT / "contracts" / "profile.example.yaml"
PROFILE_DIR = ROOT / "knowledge" / "profiles"


def _from_knowledge_module() -> dict[str, dict[str, Any]]:
    try:
        from knowledge import list_profiles  # type: ignore
    except Exception:
        return {}
    try:
        items = list_profiles() or []
    except Exception:
        return {}
    return {p["part_id"]: p for p in items if isinstance(p, dict) and p.get("part_id")}


def _from_yaml_files(folder: Path) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    if not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.yaml")) + sorted(folder.glob("*.yml")):
        try:
            for doc in yaml.safe_load_all(path.read_text()):
                if isinstance(doc, dict) and doc.get("part_id"):
                    out[doc["part_id"]] = doc
        except Exception:
            continue  # half-written file from another terminal
    return out


def _from_example() -> dict[str, dict[str, Any]]:
    docs = yaml.safe_load_all(EXAMPLE_PROFILES.read_text())
    return {d["part_id"]: d for d in docs if isinstance(d, dict) and d.get("part_id")}


def load_profiles() -> dict[str, dict[str, Any]]:
    """part_id -> profile dict. Never raises; always returns at least the example profiles."""
    merged = dict(_from_example())
    merged.update(_from_yaml_files(PROFILE_DIR))
    merged.update(_from_knowledge_module())
    return merged


def profile_for(part_id: str | None, profiles: dict[str, dict[str, Any]]) -> dict[str, Any] | None:
    if not part_id:
        return None
    if part_id in profiles:
        return profiles[part_id]
    low = part_id.lower()
    for pid, prof in profiles.items():
        aliases = [str(a).lower() for a in prof.get("aliases", [])]
        if pid.lower() == low or low in aliases:
            return prof
    return None
