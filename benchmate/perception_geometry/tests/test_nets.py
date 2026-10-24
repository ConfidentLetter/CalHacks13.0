"""Step 1: build_nets must reproduce the mock twins' nets and handle the edge cases."""
import jsonschema
import pytest

from perception_geometry import build_nets, node_of


def _as_set(nets):
    return {tuple(sorted(n["members"])) for n in nets}


def _holes_by_members(nets):
    return {tuple(sorted(n["members"])): set(n["holes"]) for n in nets}


def _wire(wid, color, a, b, conf=0.9):
    return {"id": wid, "color": color, "end_a": {"hole": a, "pixel": [0, 0]},
            "end_b": {"hole": b, "pixel": [0, 0]}, "confidence": conf}


@pytest.mark.parametrize("name", ["twin_ok", "twin_sda_swapped", "twin_5v"])
def test_mock_twins_roundtrip(mock_twins, name):
    twin = mock_twins[name]
    nets = build_nets(twin["components"], twin["wires"])
    assert _as_set(nets) == _as_set(twin["nets"])
    assert _holes_by_members(nets) == _holes_by_members(twin["nets"])


def test_nets_validate_against_schema(mock_twins, twin_schema):
    twin = dict(mock_twins["twin_ok"])
    twin["nets"] = build_nets(twin["components"], twin["wires"])
    jsonschema.validate(twin, twin_schema)
    for net in twin["nets"]:
        assert net["id"].startswith("net_")
        assert net["holes"] == sorted(net["holes"])
        assert net["members"] == sorted(net["members"])


def test_sda_swapped_differs_from_ok(mock_twins):
    ok = _as_set(build_nets(mock_twins["twin_ok"]["components"], mock_twins["twin_ok"]["wires"]))
    sw = _as_set(build_nets(mock_twins["twin_sda_swapped"]["components"], mock_twins["twin_sda_swapped"]["wires"]))
    assert ("bme280_1.SDA", "esp32_1.GPIO21") in ok
    assert ("bme280_1.SDA", "esp32_1.GPIO22") in sw


def test_node_of():
    assert node_of("A5") == node_of("E5") == "R5L"
    assert node_of("F5") == node_of("J5") == "R5R"
    assert node_of("A5") != node_of("F5")
    assert node_of("A5") != node_of("A6")
    assert node_of("RAIL_TOP_PLUS") == "RAIL_TOP_PLUS"
    assert node_of(None) is None
    with pytest.raises(ValueError):
        node_of("Z99")


COMP = [{"id": "u1", "part_id": "x", "bbox": [0, 0, 1, 1], "confidence": 1.0,
         "pins": [{"name": "P1", "hole": "C10"}, {"name": "P2", "hole": "C20"}, {"name": "NC", "hole": None}]}]


def test_wire_with_offboard_end_does_not_connect():
    nets = build_nets(COMP, [_wire("w1", "red", "A10", None)])
    by = _holes_by_members(nets)
    assert by[("u1.P1",)] == {"A10", "C10"}          # hole still recorded on the node
    assert ("u1.P1", "u1.P2") not in by


def test_pin_with_none_hole_is_ignored():
    nets = build_nets(COMP, [])
    assert _as_set(nets) == {("u1.P1",), ("u1.P2",)}
    assert all("u1.NC" not in n["members"] for n in nets)


def test_rail_to_rail_wire_merges_rails():
    comp = [{"id": "u1", "part_id": "x", "bbox": [0, 0, 1, 1], "confidence": 1.0,
             "pins": [{"name": "A", "hole": "A1"}, {"name": "B", "hole": "A2"}]}]
    wires = [_wire("w1", "red", "RAIL_TOP_PLUS", "RAIL_BOTTOM_PLUS"),
             _wire("w2", "red", "B1", "RAIL_TOP_PLUS"),
             _wire("w3", "red", "B2", "RAIL_BOTTOM_PLUS")]
    nets = build_nets(comp, wires)
    assert _as_set(nets) == {("u1.A", "u1.B")}
    assert {"RAIL_TOP_PLUS", "RAIL_BOTTOM_PLUS", "A1", "A2", "B1", "B2"} <= set(nets[0]["holes"])


def test_two_wires_sharing_a_hole():
    wires = [_wire("w1", "red", "A10", "A30"), _wire("w2", "blue", "A30", "A20")]
    nets = build_nets(COMP, wires)
    assert _as_set(nets) == {("u1.P1", "u1.P2")}


def test_dangling_wire_without_pins_is_not_a_net():
    nets = build_nets(COMP, [_wire("w1", "red", "A50", "A60")])
    assert _as_set(nets) == {("u1.P1",), ("u1.P2",)}


def test_ids_are_stable_and_sorted():
    nets = build_nets(COMP, [])
    assert [n["id"] for n in nets] == ["net_1", "net_2"]
    assert nets[0]["members"] == ["u1.P1"]
