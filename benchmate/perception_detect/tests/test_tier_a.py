"""Step 2: registrations -> components through T1's hole_to_pixel / pixel_to_hole."""
import json

import perception_detect as pd
import perception_detect.registration as reg
from perception_detect.geometry_bridge import IDENTITY, hole_to_pixel, pitch_px, snap_to_hole
from perception_detect.schema import validate_twin
from perception_detect.tier_a import stale_registrations, tier_a_components

H = IDENTITY


def px(hole):
    p = hole_to_pixel(hole, H)
    assert p is not None, "T1 hole_to_pixel unavailable"
    return p


def test_snap_round_trip_with_jitter():
    x, y = px("B40")
    assert snap_to_hole((x + 3, y - 2), H) == "B40"
    assert snap_to_hole((x + 0.45 * pitch_px(H), y), H) == "B40"
    assert snap_to_hole((-10_000, -10_000), H) is None


def test_registered_bme280_row_at_b40(reg_path):
    pd.register("bme280", 0, px("B40"))
    comps = tier_a_components(H)
    assert len(comps) == 1
    c = comps[0]
    assert c["id"] == "bme280_1" and c["part_id"] == "bme280" and c["confidence"] == 0.99
    assert [(p["name"], p["hole"]) for p in c["pins"]] == [
        ("VIN", "B40"), ("GND", "B41"), ("SCL", "B42"), ("SDA", "B43")]
    x, y, w, h = c["bbox"]
    pad = 1.5 * pitch_px(H)
    assert abs(x - (px("B40")[0] - pad)) < 1 and abs((x + w) - (px("B43")[0] + pad)) < 1
    assert w > 3 * pitch_px(H) and h > 2 * pad


def test_esp32_two_clicks_reproduce_mock_pins(reg_path):
    pd.register("esp32-devkitc", 0, px("C1"))
    pd.register("esp32-devkitc", 1, px("J20"))
    pd.register("bme280", 0, px("B40"))
    comps = {c["id"]: c for c in tier_a_components(H)}
    assert set(comps) == {"esp32_1", "bme280_1"}
    pins = {(p["name"], p["hole"]) for p in comps["esp32_1"]["pins"]}  # GND appears in both rows
    mock = json.loads(pd.twin.MOCK_TWIN_OK_PATH.read_text())
    for p in mock["components"][0]["pins"]:          # 3V3 C1, GND C14, 5V C19, GPIO21 J15, GPIO22 J18
        assert (p["name"], p["hole"]) in pins, p
    assert len(comps["esp32_1"]["pins"]) == 38


def test_components_validate_inside_twin(reg_path, tmp_path):
    reg.set_current_homography(H, calibrated=True)
    pd.register("bme280", 0, px("B40"))
    comps = pd.detect_components(str(tmp_path / "x.jpg"))
    twin = {**pd.twin.mock_twin("x"), "components": comps}
    assert validate_twin(twin) == []
    assert [c["id"] for c in comps] == ["bme280_1"]


def test_registration_survives_restart_and_is_reused(reg_path):
    pd.register("bme280", 0, px("B40"))
    import importlib
    importlib.reload(reg)
    assert [p["hole"] for p in tier_a_components(H)[0]["pins"]] == ["B40", "B41", "B42", "B43"]


def test_registration_survives_camera_drift_and_reports_big_moves(reg_path):
    reg.set_current_homography(H)
    pd.register("bme280", 0, px("B40"))
    drift = [[1.0, 0.0, 0.4], [0.0, 1.0, -0.3], [0.0, 0.0, 1.0]]   # re-calibration jitter
    assert [p["hole"] for p in tier_a_components(drift)[0]["pins"]] == ["B40", "B41", "B42", "B43"]
    assert stale_registrations(drift) == []
    moved = [[1.0, 0.0, 3 * pitch_px(H)], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
    assert [p["hole"] for p in tier_a_components(moved)[0]["pins"]] == ["B40", "B41", "B42", "B43"]
    assert [r["part_id"] for r in stale_registrations(moved)] == ["bme280"]


def test_click_before_calibration_is_snapped_later(reg_path):
    reg.set_current_homography(None)
    pd.register("bme280", 0, px("B40"))      # hole unknown at click time
    assert reg.load_registrations()[0]["hole"] is None
    assert [p["hole"] for p in tier_a_components(H)[0]["pins"]] == ["B40", "B41", "B42", "B43"]


def test_off_board_click_and_unknown_part_are_skipped(reg_path):
    pd.register("bme280", 0, (-5000.0, -5000.0))
    pd.register("hc-sr04", 0, px("B10"))
    pd.register("bme280", 7, px("B10"))  # no such footprint row
    assert tier_a_components(H) == []


def test_mock_mode_returns_mock_components(monkeypatch, tmp_path):
    monkeypatch.setenv("BM_MOCK", "1")
    comps = pd.detect_components(str(tmp_path / "x.jpg"))
    assert {c["id"] for c in comps} == {"esp32_1", "bme280_1"}
