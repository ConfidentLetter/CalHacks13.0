"""T3 reasoning — public API per contracts/interfaces.md.

    run_checks(twin, serial)                         -> diagnosis (proactive, rules only)
    answer(question, twin, serial, frame_path)       -> diagnosis (answer, rules only, <300 ms)
    refine(question, twin, serial, frame_path, rule_diagnosis) -> diagnosis (answer, model-grounded)
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

from reasoning._telemetry import timed
from reasoning.schema import assert_valid

_MOCK_DIAG = Path(__file__).resolve().parent.parent / "mocks" / "diagnosis_sda_swapped.json"


def _mock_diagnosis(frame_id: str, mode: str, question: str | None) -> dict:
    """Step 1 stub body: the mock diagnosis adapted to this frame/mode."""
    d = copy.deepcopy(json.loads(_MOCK_DIAG.read_text()))
    d["frame_id"] = frame_id
    d["mode"] = mode
    d["question"] = question
    return assert_valid(d)


def run_checks(twin: dict, serial: list[str]) -> dict:
    """Proactive. Deterministic profile checks only (no API call). Returns diagnosis.schema.json, mode='proactive'."""
    lat: dict[str, float] = {}
    with timed("run_checks", lat):
        d = _mock_diagnosis(twin.get("frame_id", "unknown"), "proactive", None)
    d["latency_ms"] = {**d.get("latency_ms", {}), **lat}
    return d


def answer(question: str, twin: dict, serial: list[str], frame_path: str) -> dict:
    """Reactive, phase 1: rule findings for the question, no API call (<300 ms). diagnosis.schema.json, mode='answer'."""
    lat: dict[str, float] = {}
    with timed("answer_phase1", lat):
        d = _mock_diagnosis(twin.get("frame_id", "unknown"), "answer", question)
    d["latency_ms"] = {**d.get("latency_ms", {}), **lat}
    return d


def refine(question: str, twin: dict, serial: list[str], frame_path: str, rule_diagnosis: dict) -> dict:
    """Reactive, phase 2: vision-model answer, grounded and verified. Same frame_id as rule_diagnosis.
    Must never return something worse than rule_diagnosis: on any failure, return rule_diagnosis."""
    return rule_diagnosis


__all__ = ["run_checks", "answer", "refine"]
