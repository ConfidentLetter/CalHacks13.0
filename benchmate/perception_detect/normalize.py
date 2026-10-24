"""normalize_part: map printed label text to a profile part_id (Step 1: exact alias match;
Step 3 adds rapidfuzz fuzzy matching)."""
from __future__ import annotations

import re

from .profiles import list_profiles

_STRIP_RE = re.compile(r"[\s\-_]+")


def canon(text: str) -> str:
    """Uppercase and strip spaces/dashes/underscores: 'GY-BME 280' -> 'GYBME280'."""
    return _STRIP_RE.sub("", str(text)).upper()


def alias_table() -> list[tuple[str, str]]:
    """[(canonical_alias, part_id), ...] including the part_id itself as an alias."""
    rows: list[tuple[str, str]] = []
    for p in list_profiles():
        pid = p.get("part_id")
        if not pid:
            continue
        names = [pid, *(p.get("aliases") or [])]
        rows.extend((canon(n), pid) for n in names if n)
    return rows


def normalize_part(label_text: str) -> str | None:
    """'GY-BME280', 'BME 280' -> 'bme280'. None if below match threshold."""
    if not label_text or not str(label_text).strip():
        return None
    key = canon(label_text)
    for alias, pid in alias_table():
        if alias == key or (len(alias) >= 5 and alias in key):
            return pid
    return None
