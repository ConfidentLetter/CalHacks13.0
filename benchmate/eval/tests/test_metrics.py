import copy
import json
from pathlib import Path

import metrics as M

MOCKS = Path(__file__).resolve().parents[2] / "mocks"
OK = json.loads((MOCKS / "twin_ok.json").read_text())
SWAPPED = json.loads((MOCKS / "twin_sda_swapped.json").read_text())
FIVE_V = json.loads((MOCKS / "twin_5v.json").read_text())


def test_identical_twins_score_perfect():
    assert M.component_accuracy(OK, OK).value == 1.0
    assert M.wire_endpoint_accuracy(OK, OK).value == 1.0
    assert M.nets_equal(OK, OK) is True


def test_swapped_wires_lower_wire_and_net_scores():
    # the yellow and green wires each keep one end and lose the other: 10/12 endpoints
    r = M.wire_endpoint_accuracy(OK, SWAPPED)
    assert (r.hits, r.total) == (10, 12)
    assert M.nets_equal(OK, SWAPPED) is False
    assert M.component_accuracy(OK, SWAPPED).value == 1.0


def test_wire_matching_is_one_to_one_and_orientation_free():
    def tw(*pairs):
        return {"wires": [{"end_a": {"hole": a}, "end_b": {"hole": b}} for a, b in pairs]}
    assert M.wire_endpoint_accuracy(tw(("A1", "B2")), tw(("B2", "A1"))).hits == 2
    assert M.wire_endpoint_accuracy(tw(("A1", "B2"), ("C3", "D4")), tw(("A1", "C3"), ("B2", "D4"))).hits == 2
    r = M.wire_endpoint_accuracy(tw(("A1", None)), tw(("A1", "B2")))
    assert (r.hits, r.total) == (1, 2)
    assert M.wire_endpoint_accuracy(tw(("A1", "B2")), tw(("A1", "B2"), ("X1", "X2"))).hits == 2


def test_extra_components_counted():
    pred = copy.deepcopy(OK)
    pred["components"].append({**OK["components"][1], "id": "bme280_2"})
    assert M.extra_components(OK, pred) == 1
    assert M.extra_components(OK, OK) == 0


def test_5v_board_has_different_endpoints():
    r = M.wire_endpoint_accuracy(OK, FIVE_V)
    assert r.total == 12 and r.hits == 11  # one RAIL_TOP_PLUS endpoint moved to RAIL_BOTTOM_PLUS
    assert M.nets_equal(OK, FIVE_V) is False


def test_component_requires_part_id_and_every_pin():
    pred = copy.deepcopy(OK)
    pred["components"][1]["pins"][0]["hole"] = "B39"
    assert M.component_accuracy(OK, pred).hits == 1
    pred = copy.deepcopy(OK)
    pred["components"][1]["part_id"] = None
    assert M.component_accuracy(OK, pred).hits == 1
    pred = copy.deepcopy(OK)
    pred["components"][1]["pins"].append({"name": "EXTRA", "hole": "B44"})  # extra pins are fine
    assert M.component_accuracy(OK, pred).hits == 2


def test_missing_components_count_against_total():
    pred = {"components": [], "wires": [], "nets": []}
    r = M.component_accuracy(OK, pred)
    assert (r.hits, r.total) == (0, 2)
    assert M.wire_endpoint_accuracy(OK, pred).value == 0.0
    assert M.nets_equal(OK, pred) is False


def test_single_member_nets_are_ignored_for_net_equality():
    pred = copy.deepcopy(OK)
    pred["nets"] = [n for n in pred["nets"] if len(n["members"]) >= 2]
    assert M.nets_equal(OK, pred) is True


def test_diagnosis_equal():
    diag = {"findings": [{"id": "supply_voltage", "severity": "error"},
                         {"id": "ground", "severity": "ok"}]}
    assert M.diagnosis_equal(["supply_voltage"], diag) is True
    assert M.diagnosis_equal([], diag) is False
    assert M.diagnosis_equal(None, diag) is None
    assert M.diagnosis_equal(["x"], None) is None          # T3 not available: not counted
    assert M.diagnosis_equal(["x"], None, failed=True) is False   # crash: a miss
    assert M.diagnosis_equal(None, None, failed=True) is None


def test_percentile_and_empty():
    assert M.percentile([], 50) is None
    assert M.percentile([5.0], 90) == 5.0
    assert M.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 50) == 5   # nearest rank: ceil(5) = 5th
    assert M.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 90) == 9
    assert M.percentile([1, 2, 3], 50) == 2 and M.percentile([1, 2, 3], 100) == 3
    assert M.Ratio(0, 0).value is None
