import json

import perception_detect.registration as reg


def test_register_persists_to_json(reg_path):
    reg.register("bme280", 0, (100.0, 200.0), path=reg_path)
    data = json.loads(reg_path.read_text())
    assert data == [{"part_id": "bme280", "row_index": 0, "pixel": [100.0, 200.0],
                     "end_pixel": None, "homography_hash": None}]


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


def test_stale_when_homography_changes(reg_path):
    H1 = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
    H2 = [[2, 0, 5], [0, 2, 5], [0, 0, 1]]
    reg.set_current_homography(H1)
    reg.register("bme280", 0, (1, 1), path=reg_path)
    r = reg.load_registrations(reg_path)[0]
    assert r["homography_hash"] == reg.homography_hash(H1)
    assert reg.is_stale(r, H1) is False
    assert reg.is_stale(r, H2) is True
    reg.set_current_homography(None)


def test_bad_input_raises(reg_path):
    import pytest
    with pytest.raises(ValueError):
        reg.register("", 0, (1, 1), path=reg_path)
    with pytest.raises(ValueError):
        reg.register("bme280", -1, (1, 1), path=reg_path)
    with pytest.raises(ValueError):
        reg.register("bme280", 0, "nope", path=reg_path)  # type: ignore[arg-type]
