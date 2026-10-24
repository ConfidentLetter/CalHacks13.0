"""Assemble a diagnosis: rules -> serial evidence -> citations -> confidence gating -> schema."""
from __future__ import annotations

import re
import time
from typing import Any

from reasoning import serial_evidence as se
from reasoning._telemetry import timed
from reasoning.citations import cite_finding
from reasoning.config import CONFIRM_THRESHOLD, SEARCH_BUDGET_MS
from reasoning.profiles import load_profiles
from reasoning.rules import resolve, run_rules, strip_meta
from reasoning.schema import assert_valid
from reasoning.twin_view import TwinIndex

_WORD = re.compile(r"[a-z0-9]+")


def confirmation_prompt(idx: TwinIndex, finding: dict[str, Any]) -> dict[str, str] | None:
    """When a finding rests on a weak element, ask about that element instead of asserting."""
    weakest = idx.weakest(finding["_meta"].get("depends_on", []))
    if weakest is None or weakest[1] >= CONFIRM_THRESHOLD:
        return None
    element_id = weakest[0]
    if element_id in idx.wires:
        wire = idx.wires[element_id]
        hole = finding["_meta"].get("far_hole") if finding["_meta"].get("wire_id") == element_id else None
        hole = hole or wire["end_b"].get("hole") or wire["end_a"].get("hole") or "that hole"
        prompt = f"Is the {wire.get('color', '')} wire in {hole}?".replace("  ", " ")
    else:
        comp = idx.components[element_id]
        prompt = f"Is {element_id} really a {comp.get('part_id') or 'known part'}?"
    return {"element_id": element_id, "prompt": f"{prompt} If so: {finding['title']}."}


def gate_by_confidence(idx: TwinIndex, findings: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    kept, asks = [], []
    for f in findings:
        ask = confirmation_prompt(idx, f)
        (asks if ask else kept).append(ask or f)
    return kept, asks


def rank_for_question(question: str | None, findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Stable re-order: within a severity, findings sharing words with the question come first."""
    if not question:
        return findings
    q = set(_WORD.findall(question.lower())) | ({"i2c", "sda", "scl"} if re.search(r"read|respond|i2c|sensor|data", question, re.I) else set()) \
        | ({"supply", "power", "vin", "3v3", "5v"} if re.search(r"power|volt|hot|smoke|5v|3\.3", question, re.I) else set())
    order = {"error": 0, "warning": 1, "info": 2, "ok": 3}

    def score(f: dict[str, Any]) -> tuple[int, int]:
        words = set(_WORD.findall(f"{f['id']} {f['title']} {f['explanation']}".lower()))
        return (order.get(f["severity"], 9), -len(q & words))

    return sorted(findings, key=score)


def build_diagnosis(twin: dict[str, Any], serial: list[str] | None, mode: str,
                    question: str | None = None, stage: str = "run_checks") -> dict[str, Any]:
    """The whole deterministic pipeline. No API calls. Validates before returning."""
    lat: dict[str, float] = {}
    with timed(stage, lat, frame_id=twin.get("frame_id")):
        profiles = load_profiles()
        with timed("rules", lat):
            findings, confirmations = run_rules(twin, profiles)
        idx = TwinIndex(twin)
        res = resolve(twin, profiles)
        periph_ids = [p.id for p in res.peripherals]

        evidence = se.classify(serial)
        findings = se.attach_serial(findings, evidence)
        has_error = any(f["severity"] == "error" for f in findings)
        if not has_error:
            extra = se.sensor_ok_finding(evidence, periph_ids)
            if extra:
                findings = findings + [extra]
        if not any(se.is_i2c_finding(f) for f in findings):
            hedge = se.serial_only_i2c_finding(evidence, periph_ids)
            if hedge:
                findings = findings + [hedge]

        with timed("search", lat):
            deadline = time.perf_counter() + SEARCH_BUDGET_MS / 1000.0
            findings = [cite_finding(f, deadline) for f in findings]

        findings, asks = gate_by_confidence(idx, findings)
        findings = rank_for_question(question, findings)

    diagnosis = {
        "frame_id": twin.get("frame_id", "unknown"),
        "mode": mode,
        "question": question,
        "findings": [strip_meta(f) for f in findings],
        "needs_user_confirmation": confirmations + asks,
        "latency_ms": {f"{k}_ms" if not k.endswith("_ms") else k: v for k, v in lat.items()},
    }
    return assert_valid(diagnosis)
