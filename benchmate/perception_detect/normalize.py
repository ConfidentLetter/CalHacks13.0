"""normalize_part: map printed label text to a profile part_id with rapidfuzz."""
from __future__ import annotations

import re
import time

from rapidfuzz import fuzz

from .profiles import list_profiles

MATCH_THRESHOLD = 85
_STRIP_RE = re.compile(r"[\s\-_]+")
_SEP_RE = re.compile(r"[\-_/]+")


def canon(text: str) -> str:
    """Uppercase and strip spaces/dashes/underscores: 'GY-BME 280' -> 'GYBME280'."""
    return _STRIP_RE.sub("", str(text)).upper()


def tokens(text: str) -> str:
    """Uppercase, dashes/underscores -> spaces, collapsed whitespace: 'GY-BME280' -> 'GY BME280'."""
    return " ".join(_SEP_RE.sub(" ", str(text)).upper().split())


_ALIAS_TTL_S = 30.0
_alias_cache: tuple[float, list[tuple[str, str]]] | None = None


def alias_table() -> list[tuple[str, str]]:
    """[(alias, part_id), ...] including the part_id itself as an alias. Cached for 30 s so T4 can
    edit profiles while we run without a restart."""
    global _alias_cache
    now = time.monotonic()
    if _alias_cache is not None and now - _alias_cache[0] < _ALIAS_TTL_S:
        return _alias_cache[1]
    rows: list[tuple[str, str]] = []
    for p in list_profiles():
        pid = p.get("part_id")
        if not pid:
            continue
        rows.extend((str(n), pid) for n in [pid, *(p.get("aliases") or [])] if n)
    _alias_cache = (now, rows)
    return rows


def score(label_text: str, alias: str) -> float:
    """Best of token-set similarity (handles extra words like '3.3') and compact-string similarity
    (handles 'bme 280' vs 'BME280'). 0..100."""
    return max(
        fuzz.token_set_ratio(tokens(label_text), tokens(alias)),
        fuzz.ratio(canon(label_text), canon(alias)),
    )


def best_match(label_text: str) -> tuple[str | None, float]:
    """(part_id, score) of the best alias; (None, 0) for empty input."""
    if not label_text or not str(label_text).strip():
        return None, 0.0
    best_pid, best = None, 0.0
    for alias, pid in alias_table():
        s = score(label_text, alias)
        if s > best:
            best_pid, best = pid, s
    return best_pid, best


def normalize_part(label_text: str) -> str | None:
    """'GY-BME280', 'BME 280' -> 'bme280'. None if below match threshold."""
    pid, s = best_match(label_text)
    return pid if pid is not None and s >= MATCH_THRESHOLD else None
