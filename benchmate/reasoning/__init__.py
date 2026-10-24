"""T3 reasoning — public API per contracts/interfaces.md.

    run_checks(twin, serial)                         -> diagnosis (proactive, rules only, no API)
    answer(question, twin, serial, frame_path)       -> diagnosis (answer, rules only, <300 ms)
    refine(question, twin, serial, frame_path, rule_diagnosis) -> diagnosis (answer, model-grounded)
"""
from __future__ import annotations

from reasoning.diagnosis import build_diagnosis


def run_checks(twin: dict, serial: list[str]) -> dict:
    """Proactive. Deterministic profile checks only (no API call). Returns diagnosis.schema.json, mode='proactive'."""
    return build_diagnosis(twin, serial, mode="proactive", stage="run_checks")


def answer(question: str, twin: dict, serial: list[str], frame_path: str) -> dict:
    """Reactive, phase 1: rule findings for the question, no API call (<300 ms). diagnosis.schema.json, mode='answer'."""
    return build_diagnosis(twin, serial, mode="answer", question=question, stage="answer_phase1")


def refine(question: str, twin: dict, serial: list[str], frame_path: str, rule_diagnosis: dict) -> dict:
    """Reactive, phase 2: vision-model answer, grounded and verified. Same frame_id as rule_diagnosis.
    Must never return something worse than rule_diagnosis: on any failure, return rule_diagnosis."""
    try:
        from reasoning.refiner import refine as _refine  # Step 4; optional until it lands
    except Exception:
        return rule_diagnosis
    try:
        return _refine(question, twin, serial, frame_path, rule_diagnosis)
    except Exception:
        return rule_diagnosis


def warmup() -> dict[str, float]:
    """Pre-load profiles, the example bank and T4's search index (its first call is slow). T5: call at startup."""
    import time
    from reasoning import citations
    from reasoning.examples import load_examples
    from reasoning.profiles import load_profiles

    out: dict[str, float] = {}
    t = time.perf_counter()
    profiles = load_profiles()
    load_examples()
    out["profiles_ms"] = round((time.perf_counter() - t) * 1000, 1)
    t = time.perf_counter()
    for pid, prof in profiles.items():
        if prof.get("datasheet"):
            citations.safe_search(pid, "supply voltage", k=1)
    out["search_ms"] = round((time.perf_counter() - t) * 1000, 1)
    return out


__all__ = ["run_checks", "answer", "refine", "warmup"]
