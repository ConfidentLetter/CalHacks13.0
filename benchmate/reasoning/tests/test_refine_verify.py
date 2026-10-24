"""Steps 4-6: refine() with a fake model, grounding checks against deliberately hallucinated output."""
import copy
import json

import pytest

import reasoning
from reasoning import refiner
from reasoning.model_client import ModelReply, parse_json_object
from reasoning.schema import validation_errors

Q = "Why isn't the sensor reading?"


def reply(obj_or_text, first=120.0, total=900.0) -> ModelReply:
    text = obj_or_text if isinstance(obj_or_text, str) else json.dumps(obj_or_text)
    return ModelReply(text=text, first_token_ms=first, total_ms=total, usage={"input_tokens": 10}, model="fake")


def fake(*replies):
    """A completer that returns the given replies in order and records the calls."""
    calls = []
    it = iter(replies)

    def complete(system, messages):
        calls.append((system, messages))
        return next(it)
    complete.calls = calls
    return complete


def good_swap_finding(**over):
    f = {"id": "i2c_swapped", "severity": "error", "title": "SDA and SCL are swapped",
         "explanation": "The yellow wire w_yellow_1 goes to GPIO22 and the green wire w_green_1 to GPIO21.",
         "fix": "Swap the yellow wire (I18) and the green wire (I15)",
         "evidence": {"wires": ["w_yellow_1", "w_green_1"], "components": ["bme280_1", "esp32_1"],
                      "serial_lines": ["[i2c] no I2C devices found"], "datasheet": []},
         "confidence": 0.9}
    f.update(over)
    return f


@pytest.fixture
def rules(twin_swapped, serial_swapped):
    return reasoning.answer(Q, twin_swapped, serial_swapped, "missing_frame.jpg")


def test_public_refine_is_offline_safe(rules, twin_swapped, serial_swapped):
    out = reasoning.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules)
    assert out is rules  # no key in tests -> rule diagnosis untouched


def test_refine_happy_path(rules, twin_swapped, serial_swapped):
    model = fake(reply({"findings": [good_swap_finding()], "needs_user_confirmation": []}))
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=model)
    assert validation_errors(out) == []
    assert out["frame_id"] == rules["frame_id"] and out["mode"] == "answer" and out["question"] == Q
    assert [f["id"] for f in out["findings"]] == ["i2c_swapped"]
    assert out["findings"][0]["explanation"].startswith("The yellow wire")
    # rule citation carried over because the model gave none
    assert out["findings"][0]["evidence"]["datasheet"] == rules["findings"][0]["evidence"]["datasheet"]
    assert {"model_first_token_ms", "model_total_ms", "refine_ms", "rules_ms"} <= set(out["latency_ms"])
    assert len(model.calls) == 1
    system, messages = model.calls[0]
    assert system[-1]["cache_control"] == {"type": "ephemeral"}
    assert messages[0]["role"] == "user"


@pytest.mark.parametrize("bad, reason", [
    (good_swap_finding(id="hallucinated", explanation="The purple wire w_purple_9 is loose.", evidence={"wires": ["w_purple_9"], "components": []}), "unknown wire"),
    (good_swap_finding(id="hallucinated", explanation="SDA should go to GPIO99 on the ESP32.", evidence={"wires": [], "components": []}), "unknown pin"),
    (good_swap_finding(id="hallucinated", fix="Move the yellow wire from I18 to K99", evidence={"wires": [], "components": []}), "invalid hole"),
    (good_swap_finding(id="hallucinated", evidence={"wires": [], "components": [], "datasheet": [{"part_id": "bme280", "page": 999, "quote": "made up"}]}), "uncited page"),
    (good_swap_finding(id="hallucinated", evidence={"wires": [], "components": ["ghost_7"]}), "unknown component"),
])
def test_hallucinations_are_dropped_and_rule_restored(rules, twin_swapped, serial_swapped, bad, reason):
    model = fake(reply({"findings": [bad], "needs_user_confirmation": []}))
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=model)
    ids = [f["id"] for f in out["findings"]]
    assert "hallucinated" not in ids
    assert "i2c_swapped" in ids  # strong rule finding (conf 0.84 >= 0.8) restored
    assert validation_errors(out) == []


def test_model_saying_all_fine_does_not_beat_strong_rule(rules, twin_swapped, serial_swapped):
    ok = {"id": "looks_fine", "severity": "ok", "title": "Wiring looks correct", "explanation": "All good in the image.",
          "fix": "Nothing to do", "evidence": {"wires": [], "components": ["bme280_1"]}, "confidence": 0.7}
    model = fake(reply({"findings": [ok], "needs_user_confirmation": []}))
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=model)
    assert [f["id"] for f in out["findings"]] == ["i2c_swapped"]
    assert out["findings"][0]["fix"] == rules["findings"][0]["fix"]


def test_invalid_json_then_valid_uses_retry_with_error(rules, twin_swapped, serial_swapped):
    model = fake(reply("Sure! Here is my answer: not json"),
                 reply({"findings": [good_swap_finding()], "needs_user_confirmation": []}))
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=model)
    assert len(model.calls) == 2
    retry_messages = model.calls[1][1]
    assert retry_messages[1]["role"] == "assistant" and retry_messages[2]["role"] == "user"
    assert "rejected" in retry_messages[2]["content"]
    assert [f["id"] for f in out["findings"]] == ["i2c_swapped"]


def test_two_bad_outputs_fall_back_to_rules(rules, twin_swapped, serial_swapped):
    model = fake(reply("garbage"), reply({"findings": "nope"}))
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=model)
    assert out is rules


def test_model_exception_falls_back_to_rules(rules, twin_swapped, serial_swapped):
    def boom(system, messages):
        raise RuntimeError("network down")
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=boom)
    assert out is rules


def test_schema_violation_in_model_output_is_rejected(rules, twin_swapped, serial_swapped):
    bad = good_swap_finding(confidence=7)  # normalised to 1.0, fine; but severity bogus -> info, still valid
    bad["severity"] = "catastrophic"
    model = fake(reply({"findings": [bad], "needs_user_confirmation": [{"element_id": "nope_1", "prompt": "?"}]}))
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=model)
    assert validation_errors(out) == []
    assert out["needs_user_confirmation"] == []  # ungrounded confirmation dropped
    assert out["findings"][0]["severity"] in ("error", "info")


def test_model_confirmation_kept_when_grounded(rules, twin_swapped, serial_swapped):
    model = fake(reply({"findings": [good_swap_finding()],
                        "needs_user_confirmation": [{"element_id": "w_green_1", "prompt": "Is the green wire fully seated?"}]}))
    out = refiner.refine(Q, twin_swapped, serial_swapped, "missing_frame.jpg", rules, complete=model)
    assert out["needs_user_confirmation"] == [{"element_id": "w_green_1", "prompt": "Is the green wire fully seated?"}]


def test_parse_json_object_tolerates_fences_and_prose():
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Here you go: {"a": {"b": 2}} thanks') == {"a": {"b": 2}}
    with pytest.raises(Exception):
        parse_json_object("no json here")
