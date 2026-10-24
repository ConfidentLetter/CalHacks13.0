"""Geometry + line matching helpers shared by transcribe_page (cache) and build_page_twin (stable ids)."""
from __future__ import annotations


def iou(a: list, b: list) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


# ---------------------------------------------------------------------------------------------
# Temporal twin: match this snapshot's lines to the previous twin (stable ids, change events).
# ---------------------------------------------------------------------------------------------
from dataclasses import dataclass, field  # noqa: E402

from transcribe.align import reading_key, similarity  # noqa: E402
from transcribe.ids import new_page_id, next_line_id  # noqa: E402

MATCH_IOU = 0.5
TEXT_MATCH_SIM = 0.8
SAME_PAGE_FRACTION = 0.5
TRANSCRIPTION_KEYS = ("latex", "text", "kind", "confidence", "uncertain_spans", "parse_ok")


@dataclass
class Matched:
    lines: list[dict]
    changes: dict = field(default_factory=lambda: {"added": [], "edited": [], "removed": [], "crossed_out": []})
    page_id: str = ""
    matched_prev_ids: set = field(default_factory=set)


def _pair(new_lines: list[dict], prev_lines: list[dict]) -> dict[int, dict]:
    """new index -> previous line. IoU ≥ MATCH_IOU first (greedy, best first), then order+text."""
    pairs: dict[int, dict] = {}
    taken: set[str] = set()
    cands = sorted(((iou(n["bbox"], p["bbox"]), i, p) for i, n in enumerate(new_lines) for p in prev_lines),
                   key=lambda t: -t[0])
    for score, i, p in cands:
        if score < MATCH_IOU:
            break
        if i in pairs or p["id"] in taken:
            continue
        pairs[i], taken = p, taken | {p["id"]}
    for i, n in enumerate(new_lines):
        if i in pairs:
            continue
        for p in prev_lines:
            if p["id"] in taken:
                continue
            if p.get("order") == n.get("order") and similarity(reading_key(n), reading_key(p)) >= TEXT_MATCH_SIM:
                pairs[i], taken = p, taken | {p["id"]}
                break
    return pairs


def _same_reading(a: dict, b: dict) -> bool:
    return reading_key(a) == reading_key(b)


def match_to_previous(new_lines: list[dict], previous_twin: dict | None, now: str, quality_ok: bool = True) -> Matched:
    """Assign stable ids + first_seen/last_changed, compute changes, decide page_id."""
    prev_lines = list((previous_twin or {}).get("lines") or [])
    pairs = _pair(new_lines, prev_lines) if prev_lines else {}
    prev_page = (previous_twin or {}).get("page_id")
    same_page = bool(prev_page) and (not prev_lines or len(pairs) >= SAME_PAGE_FRACTION * len(prev_lines))
    if not same_page:
        pairs, prev_lines = {}, []  # a different page: fresh ids, nothing carried over, nothing "removed"
    out = Matched(lines=[], page_id=prev_page if same_page else new_page_id())
    used_ids = {p["id"] for p in prev_lines}
    for i, n in enumerate(new_lines):
        p = pairs.get(i)
        if p is None:
            lid = next_line_id(used_ids)
            used_ids.add(lid)
            out.lines.append({**n, "id": lid, "first_seen": now, "last_changed": now})
            out.changes["added"].append(lid)
            continue
        out.matched_prev_ids.add(p["id"])
        line = {**n, "id": p["id"], "first_seen": p.get("first_seen", now), "last_changed": p.get("last_changed", now)}
        if not _same_reading(n, p):
            failed_call = "no_reading" in ((n.get("readings") or {}).get("notes") or [])
            if (not quality_ok or failed_call) and p.get("confidence", 0) > n.get("confidence", 0):
                line = {**line, **{k: p[k] for k in TRANSCRIPTION_KEYS if k in p}}  # keep the good reading
            else:
                line["last_changed"] = now
                out.changes["edited"].append(p["id"])
        if n.get("status") == "crossed_out" and p.get("status") != "crossed_out":
            line["last_changed"] = now
            out.changes["crossed_out"].append(p["id"])
        out.lines.append(line)
    for p in prev_lines:
        if p["id"] in out.matched_prev_ids:
            continue
        if quality_ok:
            out.changes["removed"].append(p["id"])
        else:
            out.lines.append(dict(p))  # bad photo: never drop lines we had good readings for
    out.lines.sort(key=lambda l: (l.get("order", 0), l["bbox"][1]))
    return out
