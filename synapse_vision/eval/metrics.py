"""Pure metric functions for run_eval.py. No I/O, no model calls.

Bboxes are [x, y, w, h]. "pred" lines come from a page twin, "truth" lines from a truth file.
"""
from __future__ import annotations

import re
import warnings
from statistics import median

IOU_MATCH = 0.6


# ----------------------------------------------------------------------------- geometry

def iou(a: list[float], b: list[float]) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def match_lines(pred: list[dict], truth: list[dict], thresh: float = IOU_MATCH) -> dict:
    """Greedy one-to-one matching by IoU (highest first). Returns {pairs:[(pi, ti)], unmatched_pred, unmatched_truth}."""
    cands = sorted(((iou(p["bbox"], t["bbox"]), pi, ti) for pi, p in enumerate(pred) for ti, t in enumerate(truth)),
                   reverse=True)
    used_p: set[int] = set()
    used_t: set[int] = set()
    pairs: list[tuple[int, int]] = []
    for score, pi, ti in cands:
        if score < thresh:
            break
        if pi in used_p or ti in used_t:
            continue
        pairs.append((pi, ti))
        used_p.add(pi)
        used_t.add(ti)
    return {"pairs": pairs,
            "unmatched_pred": [i for i in range(len(pred)) if i not in used_p],
            "unmatched_truth": [i for i in range(len(truth)) if i not in used_t]}


def merged_line_count(pred: list[dict], truth: list[dict], cover: float = 0.5) -> int:
    """Predicted boxes that swallow two or more truth lines (each truth box ≥ `cover` inside the pred box)."""
    count = 0
    for p in pred:
        px, py, pw, ph = p["bbox"]
        inside = 0
        for t in truth:
            tx, ty, tw, th = t["bbox"]
            ix = max(0.0, min(px + pw, tx + tw) - max(px, tx))
            iy = max(0.0, min(py + ph, ty + th) - max(py, ty))
            if tw * th > 0 and (ix * iy) / (tw * th) >= cover:
                inside += 1
        if inside >= 2:
            count += 1
    return count


def reading_order_accuracy(pairs: list[tuple[int, int]], pred: list[dict], truth: list[dict]) -> float | None:
    """Fraction of matched line pairs (i, j) whose relative order agrees between prediction and truth."""
    if len(pairs) < 2:
        return None
    agree = total = 0
    for a in range(len(pairs)):
        for b in range(a + 1, len(pairs)):
            (pa, ta), (pb, tb) = pairs[a], pairs[b]
            t_sign = truth[ta].get("order", ta) - truth[tb].get("order", tb)
            p_sign = pred[pa].get("order", pa) - pred[pb].get("order", pb)
            total += 1
            agree += (t_sign > 0) == (p_sign > 0) if t_sign != 0 else 1
    return agree / total


# ----------------------------------------------------------------------------- text

def normalize(latex: str) -> str:
    """T3's normalize_latex when importable, else a conservative local version."""
    try:
        from transcribe import normalize_latex

        return normalize_latex(latex or "")
    except Exception:  # noqa: BLE001
        s = (latex or "").replace("\u00b7", "\\cdot").replace("\u2212", "-")
        s = re.sub(r"\\(left|right)", "", s)
        s = s.replace("\\cdot", "*").replace("\\times", "*")
        s = re.sub(r"\s+", "", s)
        s = re.sub(r"\{([A-Za-z0-9])\}", r"\1", s)
        return s


def cer(pred: str, truth: str) -> float:
    """Character error rate: Levenshtein(pred, truth) / len(truth). Empty truth: 0 if pred empty else 1."""
    if not truth:
        return 0.0 if not pred else 1.0
    prev = list(range(len(truth) + 1))
    for i, pc in enumerate(pred, 1):
        cur = [i]
        for j, tc in enumerate(truth, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (pc != tc)))
        prev = cur
    return prev[-1] / len(truth)


_PRIME_RE = re.compile(r"([A-Za-z])'+")
_REL_SPLIT = re.compile(r"=|\\le(?:q)?\b|\\ge(?:q)?\b|\\ne(?:q)?\b|<|>")


def _sympy_side(side: str):
    """Parse one side of a relation with SymPy's LaTeX parser; None if it will not parse."""
    s = side.strip().replace("\u2212", "-").replace("\u00b7", "\\cdot")
    s = _PRIME_RE.sub(lambda m: m.group(1) + "_{p}", s)
    s = re.sub(r"\\(?:left|right)", "", s)
    if not s:
        return None
    try:
        from sympy.parsing.latex import parse_latex
    except Exception:  # noqa: BLE001
        return None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            return parse_latex(s)
        except Exception:  # noqa: BLE001
            return None


def equivalent(a: str, b: str) -> tuple[bool, str]:
    """Mathematical equivalence (SymPy, side by side across '='); falls back to normalized exact match.

    Returns (equivalent, method) with method in {'sympy', 'exact'}.
    """
    na, nb = normalize(a), normalize(b)
    if na == nb:
        return True, "exact"
    sa, sb = _REL_SPLIT.split(a or ""), _REL_SPLIT.split(b or "")
    if len(sa) != len(sb):
        return False, "exact"
    try:
        import sympy
    except Exception:  # noqa: BLE001
        return False, "exact"
    for xa, xb in zip(sa, sb):
        ea, eb = _sympy_side(xa), _sympy_side(xb)
        if ea is None or eb is None:
            return False, "exact"
        try:
            if sympy.simplify(ea - eb) != 0:
                return False, "sympy"
        except Exception:  # noqa: BLE001
            return False, "exact"
    return True, "sympy"


# ----------------------------------------------------------------------------- per-page scoring

def score_page(pred: list[dict], truth: list[dict]) -> dict:
    """All line-level metrics for one page. `pred` boxes must already be in truth-image pixels."""
    m = match_lines(pred, truth)
    pairs = m["pairs"]
    tp = len(pairs)
    out = {
        "n_pred": len(pred), "n_truth": len(truth), "tp": tp,
        "precision": tp / len(pred) if pred else (1.0 if not truth else 0.0),
        "recall": tp / len(truth) if truth else 1.0,
        "merged": merged_line_count(pred, truth),
        "order_acc": reading_order_accuracy(pairs, pred, truth),
        "exact": 0, "cer_sum": 0.0, "crossed_correct": 0,
        "calib": {"hi": [0, 0], "mid": [0, 0], "lo": [0, 0]},  # [correct, total]
        "planted_total": 0, "planted_preserved": 0, "autocorrections": [], "planted_missed": [],
        "mismatches": [],
    }
    for pi, ti in pairs:
        p, t = pred[pi], truth[ti]
        p_lat, t_lat = p.get("latex") or p.get("text") or "", t.get("latex") or t.get("text") or ""
        exact = normalize(p_lat) == normalize(t_lat)
        out["exact"] += exact
        out["cer_sum"] += cer(normalize(p_lat), normalize(t_lat))
        out["crossed_correct"] += (p.get("status") == "crossed_out") == (t.get("status") == "crossed_out")
        conf = float(p.get("confidence", 0.0))
        bucket = "hi" if conf >= 0.8 else "mid" if conf >= 0.6 else "lo"
        out["calib"][bucket][1] += 1
        out["calib"][bucket][0] += exact
        if not exact:
            out["mismatches"].append({"truth_id": t.get("id"), "pred_id": p.get("id"), "truth": t_lat, "pred": p_lat, "confidence": conf})
        if t.get("planted_error"):
            out["planted_total"] += 1
            same_as_truth, _ = equivalent(p_lat, t_lat)
            corrected = t.get("corrected_latex") or ""
            same_as_corrected = equivalent(p_lat, corrected)[0] if corrected else False
            if same_as_truth and not same_as_corrected:
                out["planted_preserved"] += 1
            elif same_as_corrected and not same_as_truth:
                out["autocorrections"].append({"truth_id": t.get("id"), "note": t.get("planted_note", ""), "truth": t_lat, "pred": p_lat, "corrected": corrected})
            else:
                out["planted_missed"].append({"truth_id": t.get("id"), "note": t.get("planted_note", ""), "truth": t_lat, "pred": p_lat})
    for ti in m["unmatched_truth"]:
        t = truth[ti]
        if t.get("planted_error"):
            out["planted_total"] += 1
            out["planted_missed"].append({"truth_id": t.get("id"), "note": t.get("planted_note", ""), "truth": t.get("latex", ""), "pred": None, "reason": "line not detected"})
    return out


def aggregate(pages: list[dict]) -> dict:
    """Roll per-page scores up into the numbers that go in history.csv."""
    tp = sum(p["tp"] for p in pages)
    n_pred = sum(p["n_pred"] for p in pages)
    n_truth = sum(p["n_truth"] for p in pages)
    calib = {k: [sum(p["calib"][k][0] for p in pages), sum(p["calib"][k][1] for p in pages)] for k in ("hi", "mid", "lo")}
    orders = [p["order_acc"] for p in pages if p["order_acc"] is not None]
    planted_total = sum(p["planted_total"] for p in pages)
    planted_preserved = sum(p["planted_preserved"] for p in pages)
    return {
        "pages": len(pages), "lines_truth": n_truth, "lines_pred": n_pred,
        "line_precision": tp / n_pred if n_pred else None,
        "line_recall": tp / n_truth if n_truth else None,
        "merged_lines": sum(p["merged"] for p in pages),
        "order_acc": sum(orders) / len(orders) if orders else None,
        "exact_match": sum(p["exact"] for p in pages) / tp if tp else None,
        "cer": sum(p["cer_sum"] for p in pages) / tp if tp else None,
        "crossed_out_acc": sum(p["crossed_correct"] for p in pages) / tp if tp else None,
        "planted_total": planted_total, "planted_preserved": planted_preserved,
        "planted_preservation": planted_preserved / planted_total if planted_total else None,
        "autocorrections": [a for p in pages for a in p["autocorrections"]],
        "planted_missed": [a for p in pages for a in p["planted_missed"]],
        "calib_hi_acc": calib["hi"][0] / calib["hi"][1] if calib["hi"][1] else None,
        "calib_mid_acc": calib["mid"][0] / calib["mid"][1] if calib["mid"][1] else None,
        "calib_lo_acc": calib["lo"][0] / calib["lo"][1] if calib["lo"][1] else None,
        "calib_counts": {k: v[1] for k, v in calib.items()},
    }


def percentile(values: list[float], q: float) -> float | None:
    if not values:
        return None
    s = sorted(values)
    k = max(0, min(len(s) - 1, round(q * (len(s) - 1))))
    return s[k]


def p50(values: list[float]) -> float | None:
    return median(values) if values else None
