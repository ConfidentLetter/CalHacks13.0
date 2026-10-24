"""Tests for app.pipeline (Step 4) with fake capture/serial and patched module calls."""
import json
import time

import pytest

from app import modules
from app.pipeline import Pipeline


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path))
    return tmp_path


class FakeCapture:
    def __init__(self):
        self.calls = []

    def get_frame(self, high_res=False):
        self.calls.append(high_res)
        return "/tmp/fake_frame.jpg"


class FakeSerial:
    def __init__(self):
        self.replay = None
        self.lines = ["[i2c] no I2C devices found"]

    def get_recent_serial(self, seconds=10):
        return self.lines

    def set_replay(self, path, clear=True):
        self.replay = path

    def set_serial(self, port=None):
        self.replay = None


def by_type(msgs, t):
    return [m for m in msgs if m["type"] == t]


def test_run_proactive_emits_valid_twin_then_diagnosis(runtime, monkeypatch):
    monkeypatch.setattr(modules, "build_twin", lambda fp: modules.load_mock_twin("sda_swapped"))
    monkeypatch.setattr(modules, "run_checks", modules.mock_run_checks)
    out, cap, ser = [], FakeCapture(), FakeSerial()
    p = Pipeline(out.append, capture=cap, serial=ser)
    diag = p.run_proactive()
    assert cap.calls == [True]  # fresh high-res still for analysis
    twins, diags = by_type(out, "twin"), by_type(out, "diagnosis")
    assert len(twins) == 1 and len(diags) == 1
    assert modules.validation_error(modules.TWIN_VALIDATOR, twins[0]["twin"]) is None
    assert modules.validation_error(modules.DIAGNOSIS_VALIDATOR, diags[0]["diagnosis"]) is None
    assert diag["mode"] == "proactive" and diag["findings"][0]["title"] == "SDA and SCL are swapped"
    assert diags[0]["diagnosis"]["frame_id"] == twins[0]["twin"]["frame_id"]
    assert "twin" in diag["latency_ms"] and "rules" in diag["latency_ms"]
    stages = [m["stage"] for m in by_type(out, "status")]
    assert "twin" in stages and "rules" in stages
    assert not any("error" in m for m in by_type(out, "status"))


def test_module_exception_falls_back_to_mock_and_server_survives(runtime, monkeypatch):
    import perception_detect
    monkeypatch.setattr(perception_detect, "build_twin", lambda fp: 1 / 0)
    out = []
    p = Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial())
    diag = p.run_proactive()
    assert diag is not None and by_type(out, "twin")  # mock twin still broadcast
    assert modules.fallback_counts().get("perception_detect.build_twin", 0) >= 1


def test_invalid_twin_from_module_is_reported_not_fatal(runtime, monkeypatch):
    monkeypatch.setattr(modules, "build_twin", lambda fp: {"frame_id": "x", "wires": "nope"})
    monkeypatch.setattr(modules, "run_checks", lambda twin, serial: modules._empty_diagnosis("x", "proactive"))
    out = []
    Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial()).run_proactive()
    errors = [m for m in by_type(out, "status") if "error" in m]
    assert errors and errors[0]["stage"] == "twin_schema"
    assert by_type(out, "diagnosis")  # still continued


def test_ask_broadcasts_rules_then_refined_with_same_frame_id(runtime, monkeypatch):
    monkeypatch.setattr(modules, "build_twin", lambda fp: modules.load_mock_twin("sda_swapped"))
    monkeypatch.setattr(modules, "answer", modules.mock_answer)

    def refine(question, twin, serial, frame_path, rule):
        r = json.loads(json.dumps(rule))
        r["findings"][0]["fix"] = "Move the yellow wire from I18 to I15."
        return r

    monkeypatch.setattr(modules, "refine", refine)
    out = []
    p = Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial())
    final = p.ask("why isn't the sensor reading?")
    diags = by_type(out, "diagnosis")
    assert [d["phase"] for d in diags] == ["rules", "refined"]
    assert diags[0]["diagnosis"]["frame_id"] == diags[1]["diagnosis"]["frame_id"]
    assert final["findings"][0]["fix"].startswith("Move the yellow wire")
    assert final["mode"] == "answer" and final["question"] == "why isn't the sensor reading?"


def test_ask_refine_timeout_keeps_phase1(runtime, monkeypatch):
    monkeypatch.setattr(modules, "build_twin", lambda fp: modules.load_mock_twin("sda_swapped"))
    monkeypatch.setattr(modules, "answer", modules.mock_answer)

    def slow_refine(*a):
        time.sleep(0.5)
        return a[-1]

    monkeypatch.setattr(modules, "refine", slow_refine)
    out = []
    p = Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial(), refine_timeout=0.1)
    final = p.ask("why?")
    assert [d["phase"] for d in by_type(out, "diagnosis")] == ["rules"]
    assert final["mode"] == "answer"
    errs = [m for m in by_type(out, "status") if m["stage"] == "refine" and "error" in m]
    assert errs and "timeout" in errs[0]["error"]


def test_ask_refine_raising_or_wrong_frame_keeps_phase1(runtime, monkeypatch):
    monkeypatch.setattr(modules, "build_twin", lambda fp: modules.load_mock_twin("sda_swapped"))
    monkeypatch.setattr(modules, "answer", modules.mock_answer)
    monkeypatch.setattr(modules, "refine", lambda *a: {**a[-1], "frame_id": "other"})
    out = []
    final = Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial()).ask("why?")
    assert [d["phase"] for d in by_type(out, "diagnosis")] == ["rules"]
    assert final["frame_id"] != "other"


def test_ask_empty_question_rejected(runtime):
    with pytest.raises(ValueError):
        Pipeline(lambda m: None, capture=FakeCapture(), serial=FakeSerial()).ask("   ")


def test_load_scenario_switches_serial_and_runs_checks(runtime, monkeypatch):
    monkeypatch.setattr(modules, "run_checks", modules.mock_run_checks)
    out, ser = [], FakeSerial()
    p = Pipeline(out.append, capture=FakeCapture(), serial=ser, mock=True)
    d = p.load_scenario("sda_swapped")
    assert ser.replay.endswith("serial_sda_swapped.txt")
    assert d["findings"] and p.twin["_mock_scenario"] == "sda_swapped"
    d = p.load_scenario("5v")
    assert ser.replay.endswith("serial_ok.txt") and p.twin["_mock_scenario"] == "5v"
    with pytest.raises(ValueError):
        p.load_scenario("nope")
    p.set_live()
    assert p.mock is False and ser.replay is None


def test_confirm_persists_and_reruns(runtime, monkeypatch):
    monkeypatch.setattr(modules, "run_checks", modules.mock_run_checks)
    out = []
    p = Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial(), mock=True)
    p.confirm("w_yellow_1", True)
    data = json.loads((runtime / "confirmations.json").read_text())
    assert data["w_yellow_1"]["answer"] is True
    assert by_type(out, "diagnosis")


def test_confirm_requests_are_emitted(runtime, monkeypatch):
    def checks(twin, serial):
        d = modules._empty_diagnosis(twin["frame_id"], "proactive")
        d["needs_user_confirmation"] = [{"element_id": "w_green_1", "prompt": "Is the green wire on I18?"}]
        return d

    monkeypatch.setattr(modules, "run_checks", checks)
    out = []
    Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial(), mock=True).run_proactive()
    reqs = by_type(out, "confirm_request")
    assert reqs == [{"type": "confirm_request", "element_id": "w_green_1", "prompt": "Is the green wire on I18?"}]


def test_calibrate_and_register(runtime, monkeypatch):
    monkeypatch.setattr(modules, "calibrate", lambda fp, corners=None: [[2, 0, 0], [0, 2, 0], [0, 0, 1]])
    seen = []
    monkeypatch.setattr(modules, "register", lambda pid, row, px: seen.append((pid, row, px)))
    monkeypatch.setattr(modules, "run_checks", modules.mock_run_checks)
    out = []
    p = Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial(), mock=True)
    assert p.calibrate([(0, 0), (1, 0), (1, 1), (0, 1)])[0][0] == 2
    p.register("bme280", 0, (10.0, 20.0))
    assert seen == [("bme280", 0, (10.0, 20.0))]
    assert "register" in [m["stage"] for m in by_type(out, "status")]


def test_busy_guard_second_call_returns_none_then_reruns(runtime, monkeypatch):
    import threading
    gate = threading.Event()

    def slow_checks(twin, serial):
        gate.wait(1)
        return modules._empty_diagnosis(twin["frame_id"], "proactive")

    monkeypatch.setattr(modules, "run_checks", slow_checks)
    out = []
    p = Pipeline(out.append, capture=FakeCapture(), serial=FakeSerial(), mock=True)
    t = threading.Thread(target=p.run_proactive)
    t.start()
    time.sleep(0.05)
    assert p.run_proactive() is None  # busy
    gate.set()
    t.join(2)
    assert len(by_type(out, "diagnosis")) == 2  # the rerun happened after the first finished
