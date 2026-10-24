"""Per-line decision: agreement → confidence; disagreement/fractions → re-read; verbatim guard."""
from __future__ import annotations

from dataclasses import dataclass, field

from transcribe import compare, guard
from transcribe.parse import parse_ok

REREAD_SUPPORT_CAP = 0.7  # when the chosen reading is the mathematically "nicer" one, never above this
AGREED_BUT_UNVERIFIED = 0.85  # fraction line, readings agree, re-read unavailable
NEAR_UNVERIFIED = 0.6  # readings differ by a character or two, re-read unavailable: differing spans flagged


def has_fraction(*readings: dict | None) -> bool:
    return any(r and "\\frac" in (r.get("latex") or "") for r in readings)


@dataclass
class Plan:
    line_r: dict | None
    page_r: dict | None
    agree: bool
    needs_reread: bool
    near: bool = False
    forced: str | None = None  # 'A'/'B' decided without a re-read (prose-consistency rule)
    notes: list[str] = field(default_factory=list)


def plan(line_r: dict | None, page_r: dict | None, *, threshold: float, tall: bool) -> Plan:
    if line_r is None or page_r is None:
        return Plan(line_r, page_r, agree=False, needs_reread=False, notes=["single_pass"])
    agree = compare.readings_agree(line_r, page_r)
    near = (not agree) and compare.readings_near(line_r, page_r, threshold)
    forced = None if agree else compare.text_consistent_choice(line_r, page_r)
    needs = ((not agree) and forced is None) or has_fraction(line_r, page_r) or tall
    notes = [] if agree else (["near_disagree"] if near else ["disagree"])
    if forced:
        notes.append(f"prose_consistency_{forced}")
    if agree and needs:
        notes.append("fraction_or_tall_recheck")
    return Plan(line_r, page_r, agree=agree, needs_reread=needs, notes=notes, near=near, forced=forced)


def _is_blank(r: dict) -> bool:
    return bool(r.get("illegible")) and not (r.get("latex") or "").strip() and not (r.get("text") or "").strip()


def finalize(p: Plan, rr: dict | None, *, context: list[str], order: int, quality_issues: int,
             small_crop: bool) -> dict:
    """Return {latex, text, kind, status_illegible, confidence, uncertain_spans, parse_ok, readings}."""
    line_r, page_r = p.line_r, p.page_r
    if line_r is None and page_r is None:
        return _result({"latex": "", "text": "", "kind": "text", "illegible": True, "uncertain": []},
                       0.0, [], p, rr, quality_issues, small_crop, notes=["no_reading"])
    if line_r is None or page_r is None:
        only = line_r or page_r
        spans, unplaced = compare.model_spans(only)
        conf = compare.CONF_SINGLE_PASS_CAP
        return _result(only, conf, spans, p, rr, quality_issues, small_crop, unplaced=unplaced)

    other_latex = page_r.get("latex") or ""
    if p.forced and not p.needs_reread:
        final = line_r if p.forced == "A" else page_r
        conf = compare.CONF_REREAD_PICKED_LINE if p.forced == "A" else compare.CONF_REREAD_PICKED_PAGE
        mspans, unplaced = compare.model_spans(final)
        other = page_r if p.forced == "A" else line_r
        spans = compare.merge_spans(mspans, compare.diff_spans(final.get("latex") or "", other.get("latex") or ""))
        return _result(final, conf, spans, p, rr, quality_issues, small_crop, unplaced=unplaced, notes=list(p.notes))
    if not p.needs_reread:
        s1, u1 = compare.model_spans(line_r)
        s2, _ = compare.model_spans(page_r)
        spans = compare.merge_spans(s1, [s for s in s2 if s["end"] <= len(line_r.get("latex") or line_r.get("text") or "")])
        return _result(line_r, compare.CONF_AGREE, spans, p, rr, quality_issues, small_crop, unplaced=u1)

    final, conf, notes = line_r, compare.CONF_UNRESOLVED, list(p.notes)
    if rr is None:
        notes.append("reread_failed")
        conf = AGREED_BUT_UNVERIFIED if p.agree else (NEAR_UNVERIFIED if p.near else compare.CONF_UNRESOLVED)
    else:
        choice = rr.get("choice")
        if choice == "A":
            final, conf = line_r, (compare.CONF_AGREE if p.agree else compare.CONF_REREAD_PICKED_LINE)
        elif choice == "B":
            # The page reading never carries agreement-level confidence unless its latex is identical.
            same_latex = compare.same_latex(line_r, page_r)
            final, conf = page_r, (compare.CONF_AGREE if p.agree and same_latex else compare.CONF_REREAD_PICKED_PAGE)
        else:
            own = {k: rr.get(k) for k in ("latex", "text", "kind", "illegible", "uncertain")}
            # A lone third reading never outvotes two readings it matches with neither: if the re-read's own
            # transcription equals A or B after normalization, that candidate wins; otherwise keep the
            # line pass (detail crop + context) at low confidence with every differing span flagged.
            if compare.readings_agree(own, line_r):
                final, conf, choice = line_r, compare.CONF_REREAD_PICKED_LINE, "neither_matches_A"
            elif compare.readings_agree(own, page_r):
                final, conf, choice = page_r, compare.CONF_REREAD_PICKED_PAGE, "neither_matches_B"
            else:
                final, conf, choice = line_r, compare.CONF_THREE_WAY, "neither_unmatched"
                rr = {**rr, "own_reading": own}
        notes.append(f"reread_{choice}")
    final_latex = final.get("latex") or ""
    diff = compare.diff_spans(final_latex, line_r.get("latex") or "") + compare.diff_spans(final_latex, other_latex)
    if rr and rr.get("own_reading"):
        diff = diff + compare.diff_spans(final_latex, rr["own_reading"].get("latex") or "")
    mspans, unplaced = compare.model_spans(final)
    spans = compare.merge_spans(mspans, diff)

    if not p.agree:
        nicer = guard.which_is_nicer(line_r.get("latex") or "", other_latex, context)
        if nicer:
            nicer_latex = (line_r if nicer == "A" else page_r).get("latex") or ""
            chosen_is_nicer = final_latex == nicer_latex
            guard.record({"order": order, "A_line_pass": line_r.get("latex"), "B_page_pass": other_latex,
                          "nicer": nicer, "reread_choice": rr.get("choice") if rr else None,
                          "final": final_latex, "chosen_is_nicer": chosen_is_nicer, "context": context[-3:]})
            notes.append(f"verbatim_guard_nicer_{nicer}")
            if chosen_is_nicer:
                conf = min(conf, REREAD_SUPPORT_CAP)
                if not spans:
                    spans = [{"start": 0, "end": len(final_latex), "alternatives": [other_latex if nicer == "A" else line_r.get("latex") or ""]}]
    return _result(final, conf, spans, p, rr, quality_issues, small_crop, unplaced=unplaced, notes=notes)


def _result(final: dict, conf: float, spans: list[dict], p: Plan, rr: dict | None, quality_issues: int,
            small_crop: bool, *, unplaced: int = 0, notes: list[str] | None = None) -> dict:
    latex = final.get("latex") or ""
    text = final.get("text") or ""
    blank = _is_blank(final) or (not latex.strip() and not text.strip())
    ok = parse_ok(latex) if latex else False
    conf = 0.0 if blank else compare.adjust(conf, parse_ok=ok or not latex, quality_issues=quality_issues,
                                            small_crop=small_crop, unplaced=unplaced)
    kind = final.get("kind") if final.get("kind") in ("math", "text", "mixed", "diagram_label") else "text"
    return {"latex": latex, "text": text, "kind": kind, "illegible": blank, "confidence": conf,
            "uncertain_spans": spans if not blank else [], "parse_ok": ok,
            "readings": {"line": p.line_r, "page": p.page_r, "reread": rr, "notes": notes or list(p.notes)}}
