"""Compare two readings of the same line; build uncertain spans; compute confidence."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from transcribe.align import latex_key, reading_similarity, readings_equal

CONF_AGREE = 0.92
CONF_REREAD_PICKED_LINE = 0.78
CONF_REREAD_PICKED_PAGE = 0.72
CONF_REREAD_OWN = 0.65
CONF_THREE_WAY = 0.55  # line, page and re-read all differ: keep the line pass, flag everything
CONF_UNRESOLVED = 0.5
CONF_SINGLE_PASS_CAP = 0.7
PARSE_FAIL_PENALTY = 0.1
QUALITY_ISSUE_PENALTY = 0.1
SMALL_CROP_PENALTY = 0.05
UNPLACED_UNCERTAIN_PENALTY = 0.03


def readings_agree(a: dict, b: dict) -> bool:
    """Exact agreement after normalization. A single digit/sign difference is a disagreement."""
    return readings_equal(a, b)


_SQUASH_DROP = re.compile(r"\\(?:cdot|times|,|;|!|quad|qquad|left|right|text|mathrm|displaystyle)|[{}$\s]")
_SQUASH_CMD = re.compile(r"\\([A-Za-z]+)")


def squash(s: str) -> str:
    """Rough plain form shared by latex and prose: commands → their name, no braces/spaces, lower-case.
    '\\frac' and '^' survive; this is only used to test whether math text sits inside the prose text."""
    s = s.replace("\u00b7", "").replace("\u2212", "-").replace("\u2032", "'")
    s = _SQUASH_DROP.sub("", s)
    s = _SQUASH_CMD.sub(lambda m: m.group(1), s)
    s = re.sub(r"[·*]", "", s)
    return s.lower()


def latex_in_text(reading: dict) -> bool | None:
    """For a prose+math line: does the extracted latex appear contiguously inside the verbatim text?
    None when there is nothing to check (no latex or no text)."""
    latex, text = (reading.get("latex") or "").strip(), (reading.get("text") or "").strip()
    if not latex or not text:
        return None
    return squash(latex) in squash(text)


def text_consistent_choice(line_r: dict, page_r: dict) -> str | None:
    """Both readings transcribe the same prose but extracted different math from it: the disagreement is
    about extraction, not ink. Return 'A'/'B' when exactly one extraction is consistent with the prose."""
    if (line_r.get("text") or "").split() != (page_r.get("text") or "").split():
        return None
    if same_latex(line_r, page_r):
        return None
    a, b = latex_in_text(line_r), latex_in_text(page_r)
    if a is True and b is False:
        return "A"
    if b is True and a is False:
        return "B"
    return None


def same_latex(a: dict, b: dict) -> bool:
    return latex_key(a) == latex_key(b)


def readings_near(a: dict, b: dict, threshold: float) -> bool:
    """Close but not identical readings (used only to pick the fallback confidence when a re-read fails)."""
    return reading_similarity(a, b) >= threshold


def diff_spans(chosen: str, other: str) -> list[dict]:
    """Character-level differences between `chosen` and `other` as uncertain spans on `chosen`."""
    if chosen == other:
        return []
    spans = []
    for tag, i1, i2, j1, j2 in SequenceMatcher(None, chosen, other, autojunk=False).get_opcodes():
        if tag == "equal":
            continue
        spans.append({"start": i1, "end": i2, "alternatives": [other[j1:j2]]})
    return spans


def model_spans(reading: dict) -> tuple[list[dict], int]:
    """Convert the model's {span, alternatives} list to offsets in latex (or text). Returns (spans, unplaced)."""
    latex = reading.get("latex") or ""
    target = latex if latex else (reading.get("text") or "")
    spans, unplaced, cursor = [], 0, 0
    for u in reading.get("uncertain") or []:
        span = str(u.get("span") or "")
        alts = [str(a) for a in (u.get("alternatives") or []) if str(a) != span]
        if not span:
            continue
        pos = target.find(span, cursor)
        if pos < 0:
            pos = target.find(span)
        if pos < 0:
            unplaced += 1
            continue
        spans.append({"start": pos, "end": pos + len(span), "alternatives": alts})
        cursor = pos + len(span)
    return spans, unplaced


def merge_spans(*groups: list[dict]) -> list[dict]:
    seen, out = set(), []
    for g in groups:
        for s in g:
            key = (s["start"], s["end"], tuple(s["alternatives"]))
            if key not in seen:
                seen.add(key)
                out.append({"start": int(s["start"]), "end": int(s["end"]), "alternatives": list(s["alternatives"])})
    return sorted(out, key=lambda s: (s["start"], s["end"]))


def adjust(confidence: float, *, parse_ok: bool, quality_issues: int, small_crop: bool, unplaced: int) -> float:
    c = confidence
    if not parse_ok:
        c -= PARSE_FAIL_PENALTY
    c -= min(3, quality_issues) * QUALITY_ISSUE_PENALTY
    if small_crop:
        c -= SMALL_CROP_PENALTY
    c -= unplaced * UNPLACED_UNCERTAIN_PENALTY
    return round(max(0.0, min(1.0, c)), 3)
