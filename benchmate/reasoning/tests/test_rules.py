"""Step 2: rule engine on the three mocks plus edge cases. No network."""
import copy

import pytest

from reasoning.profiles import load_profiles
from reasoning.rules import run_rules, strip_meta
from reasoning.schema import load_schema
from jsonschema import Draft202012Validator


def errors(findings):
    return [f for f in findings if f["severity"] == "error"]


def test_swapped_gives_single_i2c_swapped_error(twin_swapped):
    findings, confirms = run_rules(twin_swapped)
    errs = errors(findings)
    assert [f["id"] for f in errs] == ["i2c_swapped"]
    f = errs[0]
    assert f["title"] == "SDA and SCL are swapped"
    assert "w_yellow_1" in f["evidence"]["wires"] and "w_green_1" in f["evidence"]["wires"]
    assert f["fix"] == "Swap the yellow wire (I18) and the green wire (I15)"
    assert f["confidence"] == pytest.approx(0.84)  # min(w_yellow 0.86, w_green 0.84, comps)
    assert confirms == []


def test_5v_gives_single_supply_voltage_error(twin_5v):
    findings, _ = run_rules(twin_5v)
    errs = errors(findings)
    assert [f["id"] for f in errs] == ["supply_voltage"]
    f = errs[0]
    assert "5V" in f["title"] and "3.6" in f["title"]
    assert f["fix"] == "Move the red wire from RAIL_BOTTOM_PLUS to RAIL_TOP_PLUS"
    assert "w_red_2" in f["evidence"]["wires"]
    assert f["_meta"]["source_pin"] == "5V" and f["_meta"]["safe_source"] == "3V3"


def test_ok_board_has_no_errors_or_warnings(twin_ok):
    findings, confirms = run_rules(twin_ok)
    assert [f for f in findings if f["severity"] in ("error", "warning")] == []
    assert confirms == []


def test_unknown_part_reported_once_as_info(twin_ok):
    twin = copy.deepcopy(twin_ok)
    twin["components"].append({"id": "mystery_1", "part_id": None, "label_text": "???", "bbox": [0, 0, 10, 10],
                               "pins": [], "confidence": 0.7})
    findings, _ = run_rules(twin)
    infos = [f for f in findings if f["severity"] == "info"]
    assert len(infos) == 1
    assert infos[0]["title"].startswith("Unknown part")
    assert infos[0]["evidence"]["components"] == ["mystery_1"]
    assert errors(findings) == []


def test_low_confidence_wire_lowers_finding_confidence(twin_swapped):
    twin = copy.deepcopy(twin_swapped)
    twin["wires"][4]["confidence"] = 0.4  # w_yellow_1 (SDA)
    findings, _ = run_rules(twin)
    f = errors(findings)[0]
    assert f["id"] == "i2c_swapped"
    assert f["confidence"] == pytest.approx(0.4)


def test_single_wrong_pin_gives_move_fix(twin_ok):
    """SDA moved to GPIO23 (not a swap) -> one i2c_sda error with a concrete move."""
    twin = copy.deepcopy(twin_ok)
    twin["components"][0]["pins"].append({"name": "GPIO23", "hole": "J10"})
    twin["wires"][4]["end_b"]["hole"] = "I10"
    twin["nets"] = [n for n in twin["nets"] if n["id"] != "net_3"] + [
        {"id": "net_3", "holes": ["A43", "B43", "I10", "J10"], "members": ["bme280_1.SDA", "esp32_1.GPIO23"]},
        {"id": "net_6", "holes": ["J15"], "members": ["esp32_1.GPIO21"]},
    ]
    findings, _ = run_rules(twin)
    errs = errors(findings)
    assert [f["id"] for f in errs] == ["i2c_sda"]
    assert errs[0]["title"] == "SDA is on GPIO23, should be GPIO21"
    assert errs[0]["fix"] == "Move the yellow wire from I10 to I15"


def test_missing_ground_is_error(twin_ok):
    twin = copy.deepcopy(twin_ok)
    twin["wires"] = [w for w in twin["wires"] if w["id"] != "w_black_2"]
    twin["nets"] = [n for n in twin["nets"] if n["id"] != "net_1"] + [
        {"id": "net_1", "holes": ["A14", "C14", "RAIL_TOP_MINUS"], "members": ["esp32_1.GND"]},
        {"id": "net_7", "holes": ["B41"], "members": ["bme280_1.GND"]},
    ]
    findings, _ = run_rules(twin)
    errs = errors(findings)
    assert [f["id"] for f in errs] == ["ground"]
    assert errs[0]["fix"].startswith("Add a wire from B41 to RAIL_TOP_MINUS")


def test_shorted_sources_pattern(twin_5v):
    """5V also tied to the top rail that 3V3 feeds -> '3V3 and 5V are shorted together'."""
    twin = copy.deepcopy(twin_5v)
    twin["wires"][6]["end_b"]["hole"] = "RAIL_TOP_PLUS"  # w_red_3: A19 -> top rail
    twin["wires"][1]["end_b"]["hole"] = "RAIL_TOP_PLUS"  # w_red_2 back to top rail
    twin["nets"] = [n for n in twin["nets"] if n["id"] not in ("net_4", "net_5")] + [
        {"id": "net_4", "holes": ["A1", "A19", "A40", "B40", "C1", "C19", "RAIL_TOP_PLUS"],
         "members": ["bme280_1.VIN", "esp32_1.3V3", "esp32_1.5V"]},
    ]
    findings, _ = run_rules(twin)
    ids = {f["id"] for f in errors(findings)}
    assert "supply_voltage" in ids
    short = [f for f in findings if f["id"].startswith("sources_shorted")]
    assert len(short) == 1
    assert short[0]["title"] == "3V3 and 5V are shorted together"
    assert short[0]["fix"] == "Remove the red wire between C19 and RAIL_TOP_PLUS"


def test_unplaced_pin_asks_for_confirmation(twin_ok):
    twin = copy.deepcopy(twin_ok)
    twin["components"][1]["pins"][3]["hole"] = None  # bme280 SDA unknown
    twin["nets"][2]["members"] = ["esp32_1.GPIO21"]
    findings, confirms = run_rules(twin)
    assert confirms == [{"element_id": "bme280_1", "prompt": "Which hole is bme280_1's SDA pin in?"}]
    assert "i2c_sda" not in {f["id"] for f in findings}


def test_no_mcu_warns(twin_ok):
    twin = copy.deepcopy(twin_ok)
    twin["components"] = [twin["components"][1]]
    findings, _ = run_rules(twin)
    assert [f["id"] for f in findings] == ["no_mcu"]


def test_wording_limits_and_schema_shape(twin_swapped, twin_5v, twin_ok):
    schema = load_schema("diagnosis")["properties"]["findings"]["items"]
    v = Draft202012Validator(schema)
    for twin in (twin_swapped, twin_5v, twin_ok):
        for f in run_rules(twin).findings:
            clean = strip_meta(f)
            assert list(v.iter_errors(clean)) == []
            assert len(f["title"].split()) <= 8, f["title"]
            assert len(f["fix"].split()) <= 20, f["fix"]


def test_profiles_fallback_loads_example_docs():
    profiles = load_profiles()
    assert {"bme280", "esp32-devkitc"} <= set(profiles)
    assert profiles["esp32-devkitc"]["role"] == "mcu"
