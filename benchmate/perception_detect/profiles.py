"""Access to component profiles: T4's knowledge.list_profiles/get_profile, with a fallback
to contracts/profile.example.yaml until T4 ships."""
from __future__ import annotations

import yaml

from .paths import PROFILE_EXAMPLE_PATH, PROFILES_DIR


def _load_example_profiles() -> list[dict]:
    docs = list(yaml.safe_load_all(PROFILE_EXAMPLE_PATH.read_text()))
    return [d for d in docs if isinstance(d, dict) and d.get("part_id")]


def _load_profile_dir() -> list[dict]:
    out: list[dict] = []
    if not PROFILES_DIR.is_dir():
        return out
    for path in sorted(PROFILES_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text())
        except Exception:
            continue
        if isinstance(data, dict) and data.get("part_id"):
            out.append(data)
    return out


def list_profiles() -> list[dict]:
    """All profiles. Order of preference: knowledge.list_profiles() -> knowledge/profiles/*.yaml
    -> contracts/profile.example.yaml. Never raises."""
    try:
        from knowledge import list_profiles as _t4_list  # type: ignore

        profiles = _t4_list()
        if profiles:
            return list(profiles)
    except Exception:
        pass
    from_dir = _load_profile_dir()
    if from_dir:
        return from_dir
    return _load_example_profiles()


def get_profile(part_id: str) -> dict:
    """Profile for part_id. KeyError if missing (same contract as knowledge.get_profile)."""
    try:
        from knowledge import get_profile as _t4_get  # type: ignore

        return dict(_t4_get(part_id))
    except KeyError:
        raise
    except Exception:
        pass
    for p in list_profiles():
        if p.get("part_id") == part_id:
            return p
    raise KeyError(part_id)

