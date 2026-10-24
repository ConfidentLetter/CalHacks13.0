"""Tunables for the reasoning module. No secrets here; keys come from the environment."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Below this confidence a finding is not asserted; the user is asked to confirm instead.
CONFIRM_THRESHOLD = 0.6
# Rule findings at or above this confidence are kept even if the model disagrees.
RULE_TRUMPS_MODEL_AT = 0.8

# Wording limits from the T3 prompt.
MAX_TITLE_WORDS = 8
MAX_FIX_WORDS = 20
MAX_QUOTE_CHARS = 200

SERIAL_WINDOW_LINES = 20
# Phase 1 must stay under 300 ms: give knowledge.search this long, else skip the citation (the call keeps
# running in its thread, so the next question is fast). T4's first search loads a model (~15 s cold).
SEARCH_BUDGET_MS = float(os.environ.get("BM_SEARCH_BUDGET_MS", "120"))  # shared by all citations of one diagnosis
SEARCH_K_CITATION = 3
SEARCH_K_QUESTION = 2

# Serial evidence regexes: name -> (pattern, applies_to_check_ids_or_'*')
SERIAL_PATTERNS: dict[str, str] = {
    "i2c_fail": r"no I2C devices?|not found at 0x|I2C.*(?:fail|error|timeout|NACK)",
    "i2c_ok": r"(?:device )?found at 0x[0-9a-fA-F]{2}|\bT=\s*-?\d|\bP=\s*\d|\bH=\s*\d|reading[s]? ok",
    "brownout": r"brownout|Brownout detector",
}
I2C_CHECK_IDS = {"i2c_sda", "i2c_scl", "i2c_swapped"}

BOARD_ROWS = {"breadboard_830": 63, "breadboard_400": 30}
BOARD_COLUMNS = "ABCDEFGHIJ"
RAIL_IDS = ("RAIL_TOP_PLUS", "RAIL_TOP_MINUS", "RAIL_BOTTOM_PLUS", "RAIL_BOTTOM_MINUS")


def model_name() -> str:
    return os.environ.get("BM_MODEL", "claude-sonnet-5-5")


def offline() -> bool:
    """True when the model must not be called (tests, demo backup)."""
    has_cred = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")
    return bool(os.environ.get("BM_OFFLINE")) or not has_cred
