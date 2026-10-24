"""Align page-pass lines (free-form, top-to-bottom) to T2's line list by order + string similarity.

Dynamic programming over the two sequences (Needleman–Wunsch style, gaps allowed on both sides).
Also detects a page-pass line that covers two consecutive T2 lines (T2 split a line) and the
reverse (T2 merged two lines); both are reported so NOTES can tell T2.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher

from transcribe.normalize import normalize_latex

GAP = -0.25
MIN_MATCH = 0.35


def reading_key(reading: dict) -> str:
    """The comparable string of a model reading.

    math lines: normalized latex. text/mixed lines: the plain text (prose wording is the content there,
    and models differ in how much prose they wrap in \\text{} inside latex). Falls back to whichever is non-empty.
    """
    latex = (reading.get("latex") or "").strip()
    text = " ".join((reading.get("text") or "").split()).lower()
    if reading.get("kind") in ("text", "mixed", "diagram_label") and text:
        return text
    return normalize_latex(latex) if latex else text


def latex_key(reading: dict) -> str:
    return normalize_latex((reading.get("latex") or "").strip())


def text_key(reading: dict) -> str:
    return " ".join((reading.get("text") or "").split()).lower()


def reading_similarity(a: dict, b: dict) -> float:
    """Similarity of two readings; when they disagree on `kind`, the better of latex-vs-latex and text-vs-text."""
    if a.get("kind") == b.get("kind"):
        return similarity(reading_key(a), reading_key(b))
    return max(similarity(latex_key(a), latex_key(b)), similarity(text_key(a), text_key(b)))


def readings_equal(a: dict, b: dict) -> bool:
    """Exact agreement after normalization (kind-robust)."""
    if a.get("kind") == b.get("kind"):
        return reading_key(a) == reading_key(b) and reading_key(a) != ""
    la, lb, ta, tb = latex_key(a), latex_key(b), text_key(a), text_key(b)
    return (la and la == lb) or (not la and not lb and ta and ta == tb)


def similarity(a: str, b: str) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b, autojunk=False).ratio()


@dataclass
class Alignment:
    page_index_for_line: list[int | None]
    covers_split: list[tuple[int, int, int]] = field(default_factory=list)  # (page_i, t2_i, t2_i+1)
    unmatched_page: list[int] = field(default_factory=list)


def align(page_readings: list[dict], line_readings: list[dict]) -> Alignment:
    """For each T2 line index, the page-pass index that best corresponds (or None)."""
    pk = [reading_key(r) for r in page_readings]
    lk = [reading_key(r) for r in line_readings]
    n, m = len(pk), len(lk)
    sim_cache: dict[tuple[int, int], float] = {}

    def sim(i: int, j: int) -> float:
        if (i, j) not in sim_cache:
            sim_cache[(i, j)] = reading_similarity(page_readings[i], line_readings[j]) if line_readings[j] else 0.0
        return sim_cache[(i, j)]

    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    back = [[None] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        score[i][0], back[i][0] = i * GAP, "up"
    for j in range(1, m + 1):
        score[0][j], back[0][j] = j * GAP, "left"
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            s_ = sim(i - 1, j - 1)
            diag = score[i - 1][j - 1] + (s_ if s_ >= MIN_MATCH else GAP * 2)
            up, left = score[i - 1][j] + GAP, score[i][j - 1] + GAP
            best = max(diag, up, left)
            score[i][j] = best
            back[i][j] = "diag" if best == diag else ("up" if best == up else "left")
    mapping: list[int | None] = [None] * m
    i, j = n, m
    while i > 0 or j > 0:
        move = back[i][j]
        if move == "diag":
            if sim(i - 1, j - 1) >= MIN_MATCH:
                mapping[j - 1] = i - 1
            i, j = i - 1, j - 1
        elif move == "up":
            i -= 1
        else:
            j -= 1
    # A T2 line whose own reading failed (empty dict) can still take the page line that sits
    # between its matched neighbours when exactly one page line is left there.
    for j in range(m):
        if line_readings[j] or mapping[j] is not None:
            continue
        prev_p = next((mapping[k] for k in range(j - 1, -1, -1) if mapping[k] is not None), -1)
        next_p = next((mapping[k] for k in range(j + 1, m) if mapping[k] is not None), n)
        if next_p - prev_p == 2:
            mapping[j] = prev_p + 1
    used = {p for p in mapping if p is not None}
    unmatched_page = [p for p in range(n) if p not in used]
    # Split detection: an unmatched page line that resembles two adjacent T2 lines joined.
    covers: list[tuple[int, int, int]] = []
    for p in unmatched_page:
        for j in range(m - 1):
            if similarity(pk[p], lk[j] + lk[j + 1]) >= 0.8:
                covers.append((p, j, j + 1))
    return Alignment(mapping, covers, unmatched_page)
