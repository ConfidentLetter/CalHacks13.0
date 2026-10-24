import json

import perception_detect.registration as reg


def test_register_persists_to_json(reg_path):
    reg.register("bme280", 0, (100.0, 200.0), path=reg_path)
    data = json.loads(reg_path.read_text())
    assert data == [{"part_id": "bme280", "row_index": 0, "pixel": [100.0, 200.0], "hole": None,
                     "end_pixel": None, "end_hole": None, "homography_hash": None}]


def test_register_replaces_same_part_row(reg_path):
    reg.register("bme280", 0, (1, 1), path=reg_path)
    reg.register("bme280", 0, (2, 2), path=reg_path)
    reg.register("esp32-devkitc", 1, (3, 3), path=reg_path)
    regs = reg.load_registrations(reg_path)
    assert [(r["part_id"], r["row_index"], r["pixel"]) for r in regs] == [
        ("bme280", 0, [2.0, 2.0]), ("esp32-devkitc", 1, [3.0, 3.0])]


def test_registration_survives_restart(reg_path):
    """Simulate a server restart: a fresh load from disk returns the same entries."""
    reg.register("bme280", 0, (10, 20), path=reg_path)
    import importlib
    importlib.reload(reg)
    assert reg.load_registrations(reg_path)[0]["pixel"] == [10.0, 20.0]


def test_register_snaps_hole_only_when_calibrated(reg_path):
    from perception_detect.geometry_bridge import IDENTITY, hole_to_pixel
    px = hole_to_pixel("B40", IDENTITY)
    reg.set_current_homography(IDENTITY, calibrated=False)
    reg.register("bme280", 0, px, path=reg_path)
    assert reg.load_registrations(reg_path)[0]["hole"] is None
    reg.set_current_homography(IDENTITY, calibrated=True)
    reg.register("bme280", 0, px, end_pixel=hole_to_pixel("B43", IDENTITY), path=reg_path)
    r = reg.load_registrations(reg_path)[0]
    assert (r["hole"], r["end_hole"]) == ("B40", "B43")
    assert r["homography_hash"] == reg.homography_hash(IDENTITY)


def test_stale_only_when_pixel_maps_to_another_hole(reg_path):
    from perception_detect.geometry_bridge import IDENTITY, hole_to_pixel, pitch_px
    reg.set_current_homography(IDENTITY)
    reg.register("bme280", 0, hole_to_pixel("B40", IDENTITY), path=reg_path)
    r = reg.load_registrations(reg_path)[0]
    assert reg.is_stale(r, IDENTITY) is False
    jitter = [[1, 0, 0.3], [0, 1, -0.2], [0, 0, 1]]        # sub-pixel camera drift: same hole
    assert reg.is_stale(r, jitter) is False
    shift = [[1, 0, 2 * pitch_px(IDENTITY)], [0, 1, 0], [0, 0, 1]]   # camera moved two holes
    assert reg.is_stale(r, shift) is True
    assert reg.resolve_holes(r, shift) == ("B40", None)   # but the stored hole is still used


def test_bad_input_raises(reg_path):
    import pytest
    with pytest.raises(ValueError):
        reg.register("", 0, (1, 1), path=reg_path)
    with pytest.raises(ValueError):
        reg.register("bme280", -1, (1, 1), path=reg_path)
    with pytest.raises(ValueError):
        reg.register("bme280", 0, "nope", path=reg_path)  # type: ignore[arg-type]
