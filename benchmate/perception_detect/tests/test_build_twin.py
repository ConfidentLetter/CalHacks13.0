"""Step 5: build_twin runs the real pipeline through T1, survives T1 failures, caches by frame hash."""
import json

import numpy as np
import pytest

import perception_detect as pd
import perception_detect.twin as twin_mod
from perception_detect.geometry_bridge import IDENTITY, hole_to_pixel
from perception_detect.schema import validate_twin


@pytest.fixture
def frame(tmp_path):
    import cv2

    p = tmp_path / "frame.jpg"
    cv2.imwrite(str(p), np.full((1080, 1920, 3), 180, np.uint8))
    twin_mod.clear_cache()
    # a blank frame cannot be calibrated; clicks are made under a known calibration like in the UI
    import perception_detect.registration as reg
    reg.set_current_homography(IDENTITY, calibrated=True)
    return p


def test_pipeline_twin_validates_and_has_nets(frame, monkeypatch):
    """T1's real detect_wires sees nothing on a blank frame, so inject the mock wires but keep
    T1's real tile/build_nets."""
    import perception_geometry as g

    class Geo:
        tile = staticmethod(g.tile)
        build_nets = staticmethod(g.build_nets)
        detect_wires = staticmethod(lambda *a, **k: json.loads(pd.twin.MOCK_TWIN_OK_PATH.read_text())["wires"])
    monkeypatch.setattr(twin_mod, "_geometry", lambda: Geo())
    pd.register("esp32-devkitc", 0, hole_to_pixel("C1", IDENTITY))
    pd.register("esp32-devkitc", 1, hole_to_pixel("J20", IDENTITY))
    pd.register("bme280", 0, hole_to_pixel("B40", IDENTITY))
    twin = pd.build_twin(str(frame))
    assert validate_twin(twin) == []
    assert twin["board"]["type"] == "breadboard_830"
    assert twin["calibration"] in ("markers_or_corners", "identity", "last_good")
    assert {c["id"] for c in twin["components"]} == {"esp32_1", "bme280_1"}
    mock = json.loads(pd.twin.MOCK_TWIN_OK_PATH.read_text())
    groups = lambda t: {frozenset(n["members"]) for n in t["nets"] if len(n["members"]) >= 2}
    assert groups(mock) <= groups(twin)


def test_no_registrations_gives_empty_components_but_valid_twin(frame):
    twin = pd.build_twin(str(frame))
    assert validate_twin(twin) == []
    assert twin["components"] == []


def test_cache_hit_and_invalidation_on_register(frame):
    a = pd.build_twin(str(frame))
    b = pd.build_twin(str(frame))
    assert a["frame_id"] == b["frame_id"] and a["timestamp"] == b["timestamp"]
    import perception_detect.registration as reg
    reg.set_current_homography(IDENTITY, calibrated=True)   # the blank frame left us uncalibrated
    pd.register("bme280", 0, hole_to_pixel("B40", IDENTITY))
    c = pd.build_twin(str(frame))
    assert [x["id"] for x in c["components"]] == ["bme280_1"]


def test_upstream_failures_do_not_blank_the_twin(frame, monkeypatch):
    class Broken:
        def tile(self, *a, **k): raise RuntimeError("tile exploded")
        def detect_wires(self, *a, **k): return [{"garbage": True}, {"id": "w1", "color": "red",
                                                 "end_a": {"hole": "A1"}, "end_b": {"hole": "B40"}}]
        def build_nets(self, *a, **k): raise ValueError("nets exploded")
    monkeypatch.setattr(twin_mod, "_geometry", lambda: Broken())
    pd.register("bme280", 0, hole_to_pixel("B40", IDENTITY))
    twin = pd.build_twin(str(frame))
    assert validate_twin(twin) == []
    assert [c["id"] for c in twin["components"]] == ["bme280_1"]
    assert [w["id"] for w in twin["wires"]] == ["w1"]
    assert twin["wires"][0]["end_a"]["pixel"] == list(hole_to_pixel("A1", IDENTITY))   # hole centre fills in
    assert twin["nets"] == []
    assert {"tile", "nets"} <= set(twin["errors"])  # calibrate may also fail on a blank frame


def test_missing_frame_file_still_returns_twin(tmp_path):
    twin = pd.build_twin(str(tmp_path / "missing.jpg"))
    assert validate_twin(twin) == []


def test_mock_mode(frame, monkeypatch):
    monkeypatch.setenv("BM_MOCK", "1")
    twin = pd.build_twin(str(frame))
    mock = json.loads(pd.twin.MOCK_TWIN_OK_PATH.read_text())
    assert twin["nets"] == mock["nets"] and twin["frame_id"] != mock["frame_id"]
