"""Step 2: pure pin-layout rules (no geometry involved)."""
import pytest

from perception_detect.layout import choose_direction, layout_row

BME = ["VIN", "GND", "SCL", "SDA"]
ESP_ROW0 = ["3V3", "EN", "VP", "VN", "GPIO34", "GPIO35", "GPIO32", "GPIO33", "GPIO25", "GPIO26",
            "GPIO27", "GPIO14", "GPIO12", "GND", "GPIO13", "SD2", "SD3", "CMD", "5V"]
ESP_ROW1 = ["GND", "GPIO23", "GPIO22", "TX", "RX", "GPIO21", "GND", "GPIO19", "GPIO18", "GPIO5",
            "GPIO17", "GPIO16", "GPIO4", "GPIO0", "GPIO2", "GPIO15", "SD1", "SD0", "CLK"]


def holes(row):
    return [h for _, h in row.pins]


def test_bme280_at_b40_walks_up():
    row = layout_row(BME, "B40")
    assert holes(row) == ["B40", "B41", "B42", "B43"]
    assert row.direction == 1


def test_walks_down_when_board_edge_is_hit():
    assert holes(layout_row(BME, "B62")) == ["B62", "B61", "B60", "B59"]


def test_end_click_fixes_direction():
    assert holes(layout_row(BME, "B40", end_hole="B37")) == ["B40", "B39", "B38", "B37"]
    assert holes(layout_row(BME, "B40", end_hole="B43")) == ["B40", "B41", "B42", "B43"]


def test_second_row_mirrors_to_overlap_first_row():
    """ESP32 DevKit: row 0 clicked at C1, row 1 clicked at J20 -> GPIO21 on J15, GPIO22 on J18 (mock twin)."""
    r0 = layout_row(ESP_ROW0, "C1")
    assert dict(r0.pins)["GND"] == "C14" and dict(r0.pins)["5V"] == "C19"
    r1 = layout_row(ESP_ROW1, "J20", reference_columns=r0.columns)
    assert r1.direction == -1
    d = dict(r1.pins)
    assert d["GPIO21"] == "J15" and d["GPIO22"] == "J18" and d["CLK"] == "J2"


def test_pins_off_board_become_none_not_crash():
    row = layout_row(["A", "B", "C"], "A63", end_hole="A62")  # explicit: down
    assert holes(row) == ["A63", "A62", "A61"]
    row = layout_row(["A", "B", "C", "D"], "A2", end_hole="A1")  # forced down, runs off the board
    assert holes(row) == ["A2", "A1", None, None]


def test_choose_direction_defaults():
    assert choose_direction(10, 4) == 1
    assert choose_direction(62, 4) == -1
    assert choose_direction(10, 4, reference_columns=(5, 10)) == -1
    assert choose_direction(10, 4, reference_columns=(10, 15)) == 1


def test_rail_anchor_rejected():
    with pytest.raises(ValueError):
        layout_row(BME, "RAIL_TOP_PLUS")
