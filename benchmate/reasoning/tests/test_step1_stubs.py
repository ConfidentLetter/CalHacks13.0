"""Step 1: exact signatures exist and every return validates against diagnosis.schema.json."""
import inspect

import reasoning
from reasoning.schema import validation_errors


def _sig(fn) -> str:
    return str(inspect.signature(fn, eval_str=True))


def test_signatures_match_contract():
    assert _sig(reasoning.run_checks) == "(twin: dict, serial: list[str]) -> dict"
    assert _sig(reasoning.answer) == "(question: str, twin: dict, serial: list[str], frame_path: str) -> dict"
    assert _sig(reasoning.refine) == "(question: str, twin: dict, serial: list[str], frame_path: str, rule_diagnosis: dict) -> dict"



def test_run_checks_validates_and_is_proactive(twin_swapped, serial_swapped):
    d = reasoning.run_checks(twin_swapped, serial_swapped)
    assert validation_errors(d) == []
    assert d["mode"] == "proactive"
    assert d["frame_id"] == twin_swapped["frame_id"]


def test_answer_validates_and_carries_question(twin_swapped, serial_swapped):
    d = reasoning.answer("Why isn't the sensor reading?", twin_swapped, serial_swapped, "frame.jpg")
    assert validation_errors(d) == []
    assert d["mode"] == "answer"
    assert d["question"] == "Why isn't the sensor reading?"
    assert d["frame_id"] == twin_swapped["frame_id"]


def test_refine_never_worse_than_rules(twin_swapped, serial_swapped):
    rules = reasoning.answer("why?", twin_swapped, serial_swapped, "frame.jpg")
    out = reasoning.refine("why?", twin_swapped, serial_swapped, "frame.jpg", rules)
    assert validation_errors(out) == []
    assert out["frame_id"] == rules["frame_id"]
    assert out["findings"], "refine must not drop the rule answer"
