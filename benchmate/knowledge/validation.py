"""Shared input validation. part_id is used to build file names, so it is restricted to a safe charset."""
from __future__ import annotations

import re

_PART_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")


def is_valid_part_id(part_id) -> bool:
    return isinstance(part_id, str) and bool(_PART_ID_RE.match(part_id)) and ".." not in part_id


def require_part_id(part_id) -> str:
    if not is_valid_part_id(part_id):
        raise ValueError(f"bad part_id {part_id!r}")
    return part_id
