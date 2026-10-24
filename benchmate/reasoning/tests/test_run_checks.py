"""Step 3: run_checks / answer end to end on mocks: serial evidence, citations, gating, schema, latency."""
import copy
import time

import pytest

import reasoning
from reasoning import citations
from reasoning.schema import validation_errors


def test_swapped_with_serial_attaches_lines_and_cites(twin_swapped, serial_swapped):
    d = reasoning.run_checks(twin_swapped, serial_swapped)
    assert validation_errors(d) == []
    assert d["mode"] == "proactive" and d["question"] is None
    errs = [f for f in d["findings"] if f["severity"] == "error"]
    assert [f["id"] for f in errs] == ["i2c_swapped"]
    f = errs[0]
    assert "[i2c] no I2C devices found" in f["evidence"]["serial_lines"]
    assert "_meta" not in f
    # citation comes from knowledge.search (T4 mock today): page coerced to int, quote <= 200 chars
    cite = f["evidence"]["datasheet"][0]
    assert cite["part_id"] == "bme280" and isinstance(cite["page"], int)
    assert len(cite.get("quote", "")) <= 200


def test_5v_citation_quote_contains_key_number(twin_5v):
    d = reasoning.run_checks(twin_5v, [])
    f = next(f for f in d["findings"] if f["id"] == "supply_voltage")
    cite = f["evidence"]["datasheet"][0]
    assert cite["page"] == 22  # the hit that contains the key number wins over the top hit
    assert cite["quote"] == "Supply voltage VDD: 1.71 V to 3.6 V."
    assert "You read this page" not in f["explanation"]


def test_ok_board_with_ok_serial_gives_sensor_responding(twin_ok, serial_ok):
    d = reasoning.run_checks(twin_ok, serial_ok)
    assert validation_errors(d) == []
    assert [f["severity"] for f in d["findings"]] == ["ok"]
    assert d["findings"][0]["id"] == "sensor_responding"
    assert any("T=22.41C" in l for l in d["findings"][0]["evidence"]["serial_lines"])


def test_ok_board_with_failing_serial_hedges_with_warning(twin_ok, serial_swapped):
    d = reasoning.run_checks(twin_ok, serial_swapped)
    assert [f["id"] for f in d["findings"]] == ["i2c_no_device"]
    assert d["findings"][0]["severity"] == "warning"


def test_low_confidence_wire_becomes_confirmation_not_assertion(twin_swapped, serial_swapped):
    twin = copy.deepcopy(twin_swapped)
    twin["wires"][4]["confidence"] = 0.4  # yellow SDA wire
    d = reasoning.run_checks(twin, serial_swapped)
    assert validation_errors(d) == []
    assert "i2c_swapped" not in {f["id"] for f in d["findings"]}
    assert d["needs_user_confirmation"] == [
        {"element_id": "w_yellow_1", "prompt": "Is the yellow wire in I18? If so: SDA and SCL are swapped."}
    ]


def test_search_failure_is_tolerated(monkeypatch, twin_5v):
    def boom(*a, **k):
        raise RuntimeError("index not built")
    monkeypatch.setattr(citations, "safe_search", lambda *a, **k: [])
    d = reasoning.run_checks(twin_5v, [])
    f = next(f for f in d["findings"] if f["id"] == "supply_voltage")
    assert "datasheet" not in f["evidence"]
    assert validation_errors(d) == []


def test_read_history_note(monkeypatch, twin_5v):
    monkeypatch.setattr(citations, "was_read", lambda part_id, page: True)
    d = reasoning.run_checks(twin_5v, [])
    f = next(f for f in d["findings"] if f["id"] == "supply_voltage")
    assert f["explanation"].endswith("You read this page earlier today.")


def test_non_numeric_page_label_drops_citation(monkeypatch, twin_5v):
    monkeypatch.setattr(citations, "safe_search", lambda *a, **k: [{"text": "max 3.6 V", "page": "iv"}])
    d = reasoning.run_checks(twin_5v, [])
    f = next(f for f in d["findings"] if f["id"] == "supply_voltage")
    assert "datasheet" not in f["evidence"]


def test_answer_phase1_sets_mode_question_and_ranks(twin_5v, serial_swapped):
    # 5V board + failing serial: question about reading should put the I2C hedge before nothing else... but
    # errors still outrank warnings, so supply_voltage stays first.
    d = reasoning.answer("why isn't the sensor reading?", twin_5v, serial_swapped, "frame.jpg")
    assert validation_errors(d) == []
    assert d["mode"] == "answer" and d["question"] == "why isn't the sensor reading?"
    assert d["findings"][0]["id"] == "supply_voltage"
    assert "i2c_no_device" in {f["id"] for f in d["findings"]}


def test_latency_under_300ms(twin_swapped, serial_swapped):
    reasoning.run_checks(twin_swapped, serial_swapped)  # warm caches
    t0 = time.perf_counter()
    for _ in range(5):
        d = reasoning.run_checks(twin_swapped, serial_swapped)
    per_call = (time.perf_counter() - t0) / 5 * 1000
    assert per_call < 300, per_call
    assert {"rules_ms", "search_ms", "run_checks_ms"} <= set(d["latency_ms"])


def test_trim_quote_prefers_sentence_with_key_number():
    text = "Intro sentence. Supply voltage VDD: 1.71 V to 3.6 V. Something else about VDDIO."
    assert citations.trim_quote(text, ["3.6"]) == "Supply voltage VDD: 1.71 V to 3.6 V."
    assert len(citations.trim_quote("x" * 500 + " 3.6 " + "y" * 500, ["3.6"])) <= 200


@pytest.mark.realsearch  # opt out of the suite-wide fake so we can test the budget on the real wrapper
def test_slow_search_is_skipped_within_budget(monkeypatch, twin_5v):
    import time
    from reasoning import citations

    def slow(part_id, query, k):
        time.sleep(0.6)
        return [{"text": "Supply voltage VDD 3.6 V.", "page": "22"}]

    monkeypatch.setattr(citations, "_raw_search", slow)
    monkeypatch.setattr(citations, "SEARCH_BUDGET_MS", 50.0)
    t0 = time.perf_counter()
    assert citations.citation_for("bme280", "supply voltage", ["3.6"], budget_ms=50.0) is None
    assert (time.perf_counter() - t0) < 0.4
    # without a budget the same search is used
    assert citations.citation_for("bme280", "supply voltage", ["3.6"], budget_ms=None)["page"] == 22


def test_warmup_runs_offline():
    out = reasoning.warmup()
    assert {"profiles_ms", "search_ms"} <= set(out)


@pytest.mark.realsearch
def test_cold_index_does_not_queue_searches(monkeypatch):
    """While the first search is still loading, later budgeted calls return [] at once; once it finishes, hits flow."""
    import threading, time
    from reasoning import citations

    gate = threading.Event()

    def slow(part_id, query, k):
        gate.wait(5)
        return [{"text": "Supply voltage VDD 3.6 V.", "page": "22"}]

    monkeypatch.setattr(citations, "_raw_search", slow)
    monkeypatch.setattr(citations, "_INFLIGHT", {})
    monkeypatch.setattr(citations, "_WARM", threading.Event())
    assert citations.safe_search("bme280", "q1", 3, budget_ms=30) == []          # starts the cold load
    t0 = time.perf_counter()
    assert citations.safe_search("bme280", "q2", 3, budget_ms=30) == []          # not queued: immediate
    assert (time.perf_counter() - t0) < 0.02
    gate.set()
    time.sleep(0.05)
    assert citations.safe_search("bme280", "q1", 3, budget_ms=200)[0]["page"] == "22"   # in-flight result reused
    assert citations.safe_search("bme280", "q3", 3, budget_ms=200)[0]["page"] == "22"   # warm now
