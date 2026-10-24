"""Self-correction for model output: schema, grounding against the twin, consistency with the rules."""
from __future__ import annotations

import re
from typing import Any

from reasoning.config import MAX_QUOTE_CHARS, RULE_TRUMPS_MODEL_AT
from reasoning.schema import validation_errors
from reasoning.twin_view import TwinIndex, is_valid_hole

_WIRE_TOKEN = re.compile(r"\bw_[a-z0-9]+_\d+\b", re.I)
_GPIO_TOKEN = re.compile(r"\bGPIO\s?\d{1,2}\b", re.I)
_HOLE_TOKEN = re.compile(r"\b(?:RAIL_[A-Z_]+|[A-Z]\d{1,3})\b")  # anything hole-shaped; validated below
_SEVERITIES = {"error", "warning", "info", "ok"}


def mcu_pin_names(profiles: dict[str, dict[str, Any]], twin: dict[str, Any]) -> set[str]:
    names: set[str] = set()
    for c in twin.get("components", []):
        names |= {p.get("name", "") for p in c.get("pins", [])}
    for prof in profiles.values():
        names |= set((prof.get("roles") or {}).values())
        names |= set((prof.get("sources") or {}).keys())
        for row in (prof.get("footprint") or {}).get("rows") or []:
            names |= set(row.get("pins") or [])
    return {str(n).upper() for n in names if n}


def normalize_finding(raw: Any) -> dict[str, Any] | None:
    """Coerce a model finding into schema shape; None if hopeless."""
    if not isinstance(raw, dict):
        return None
    ev = raw.get("evidence") if isinstance(raw.get("evidence"), dict) else {}
    out: dict[str, Any] = {
        "id": str(raw.get("id") or "model_finding"),
        "severity": raw.get("severity") if raw.get("severity") in _SEVERITIES else "info",
        "title": str(raw.get("title") or "").strip()[:120],
        "explanation": str(raw.get("explanation") or "").strip(),
        "fix": str(raw.get("fix") or "").strip(),
        "evidence": {},
        "confidence": max(0.0, min(1.0, float(raw.get("confidence", 0.5) or 0.0))),
    }
    for key in ("wires", "components", "serial_lines"):
        vals = ev.get(key)
        if isinstance(vals, list):
            out["evidence"][key] = [str(v) for v in vals]
    ds = ev.get("datasheet")
    if isinstance(ds, list):
        cites = []
        for c in ds:
            if not isinstance(c, dict) or c.get("part_id") is None:
                continue
            try:
                page = int(c.get("page"))
            except (TypeError, ValueError):
                continue
            cite = {"part_id": str(c["part_id"]), "page": page}
            if c.get("quote"):
                cite["quote"] = str(c["quote"])[:MAX_QUOTE_CHARS]
            cites.append(cite)
        out["evidence"]["datasheet"] = cites
    return out if out["title"] and out["explanation"] else None


def grounding_problems(f: dict[str, Any], idx: TwinIndex, pin_names: set[str],
                       offered_pages: set[tuple[str, int]]) -> list[str]:
    """Reasons a finding is not grounded in the evidence we gave the model."""
    problems: list[str] = []
    text = f"{f['title']} {f['explanation']} {f['fix']}"
    for tok in set(_WIRE_TOKEN.findall(text)) | set(f["evidence"].get("wires", [])):
        if tok not in idx.wires:
            problems.append(f"unknown wire {tok}")
    for comp in f["evidence"].get("components", []):
        if comp not in idx.components:
            problems.append(f"unknown component {comp}")
    for tok in set(_GPIO_TOKEN.findall(text)):
        if tok.replace(" ", "").upper() not in pin_names:
            problems.append(f"unknown pin {tok}")
    for hole in set(_HOLE_TOKEN.findall(f["fix"])):
        if not is_valid_hole(hole, idx.board_type):
            problems.append(f"invalid hole {hole}")
    for cite in f["evidence"].get("datasheet", []):
        if (cite["part_id"], cite["page"]) not in offered_pages:
            problems.append(f"uncited page {cite['part_id']} p.{cite['page']}")
    return problems


def _contradicts(model_findings: list[dict[str, Any]], rule_finding: dict[str, Any]) -> bool:
    """The model dropped a strong rule finding, or claims all is well while the rule says error."""
    ids = {f["id"] for f in model_findings}
    if rule_finding["id"] in ids:
        return False
    same_title = any(f["title"].lower() == rule_finding["title"].lower() for f in model_findings)
    return not same_title


def reconcile(model_findings: list[dict[str, Any]], rule_findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Keep strong rule findings the model contradicted; carry rule citations onto matching model findings."""
    by_id = {f["id"]: f for f in rule_findings}
    strong = [f for f in rule_findings if f["severity"] == "error" and f["confidence"] >= RULE_TRUMPS_MODEL_AT]
    out: list[dict[str, Any]] = []
    for f in model_findings:
        rule = by_id.get(f["id"])
        if rule and rule["evidence"].get("datasheet") and not f["evidence"].get("datasheet"):
            f = {**f, "evidence": {**f["evidence"], "datasheet": rule["evidence"]["datasheet"]}}
        if rule and rule["evidence"].get("serial_lines") and not f["evidence"].get("serial_lines"):
            f = {**f, "evidence": {**f["evidence"], "serial_lines": rule["evidence"]["serial_lines"]}}
        out.append(f)
    restored = [r for r in strong if _contradicts(out, r)]
    if restored:
        out = [f for f in out if f["severity"] != "ok"]
    order = {"error": 0, "warning": 1, "info": 2, "ok": 3}
    return sorted(restored + out, key=lambda f: order.get(f["severity"], 9))


def verify(model_obj: dict[str, Any], twin: dict[str, Any], profiles: dict[str, dict[str, Any]],
           rule_diagnosis: dict[str, Any], offered_pages: set[tuple[str, int]], question: str | None) -> tuple[dict[str, Any] | None, list[str]]:
    """Returns (diagnosis or None, log). None means the shape was unusable and the caller should retry/fall back."""
    log: list[str] = []
    raw_findings = model_obj.get("findings")
    if not isinstance(raw_findings, list):
        return None, ["findings is not a list"]
    idx = TwinIndex(twin)
    pins = mcu_pin_names(profiles, twin)
    kept: list[dict[str, Any]] = []
    for raw in raw_findings:
        f = normalize_finding(raw)
        if f is None:
            log.append("dropped malformed finding")
            continue
        probs = grounding_problems(f, idx, pins, offered_pages)
        if probs:
            log.append(f"dropped {f['id']}: " + ", ".join(probs))
            continue
        kept.append(f)
    findings = reconcile(kept, rule_diagnosis.get("findings", []))
    confirms = []
    for c in model_obj.get("needs_user_confirmation") or []:
        if isinstance(c, dict) and c.get("element_id") in (set(idx.wires) | set(idx.components)) and c.get("prompt"):
            confirms.append({"element_id": str(c["element_id"]), "prompt": str(c["prompt"])})
        else:
            log.append("dropped ungrounded confirmation")
    seen = {(c["element_id"], c["prompt"]) for c in confirms}
    confirms += [c for c in rule_diagnosis.get("needs_user_confirmation", []) if (c["element_id"], c["prompt"]) not in seen]
    diagnosis = {
        "frame_id": rule_diagnosis["frame_id"], "mode": "answer", "question": question,
        "findings": findings, "needs_user_confirmation": confirms,
        "latency_ms": dict(rule_diagnosis.get("latency_ms", {})),
    }
    errs = validation_errors(diagnosis)
    if errs:
        return None, log + [f"schema: {e}" for e in errs]
    return diagnosis, log
