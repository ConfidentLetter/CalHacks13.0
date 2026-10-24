"""Every function from contracts/interfaces.md exists with the exact signature and schema-valid output."""
import inspect
import json
import tempfile
from pathlib import Path

import jsonschema
import numpy as np
import pytest

import perception_geometry as pg


def _sig(fn):
    return [(p.name, p.kind) for p in inspect.signature(fn).parameters.values()]


def test_signatures():
    assert [n for n, _ in _sig(pg.calibrate)] == ["frame_path", "corners"]
    assert inspect.signature(pg.calibrate).parameters["corners"].default is None
    assert [n for n, _ in _sig(pg.pixel_to_hole)] == ["x", "y", "homography"]
    assert [n for n, _ in _sig(pg.hole_to_pixel)] == ["hole", "homography"]
    assert [n for n, _ in _sig(pg.tile)] == ["frame_path", "homography", "max_tiles"]
    assert inspect.signature(pg.tile).parameters["max_tiles"].default == 6
    assert [n for n, _ in _sig(pg.detect_wires)] == ["frame_path", "homography", "exclude_boxes"]
    assert inspect.signature(pg.detect_wires).parameters["exclude_boxes"].default is None
    assert [n for n, _ in _sig(pg.build_nets)] == ["components", "wires"]
    assert issubclass(pg.CalibrationError, Exception)


@pytest.fixture
def blank_frame(tmp_path):
    import cv2
    p = tmp_path / "blank.jpg"
    cv2.imwrite(str(p), np.full((720, 1280, 3), 200, np.uint8))
    return str(p)


def test_detect_wires_output_validates(blank_frame, twin_schema, mock_twins):
    H = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
    wires = pg.detect_wires(blank_frame, H)
    twin = dict(mock_twins["twin_ok"])
    twin["wires"] = wires
    twin["nets"] = pg.build_nets(twin["components"], wires)
    jsonschema.validate(twin, twin_schema)
    for w in wires:
        assert w["id"].startswith("w_")
        assert 0.0 <= w["confidence"] <= 1.0


def test_tile_output_shape(blank_frame):
    H = [[1.0, 0, 0], [0, 1.0, 0], [0, 0, 1.0]]
    tiles = pg.tile(blank_frame, H, max_tiles=6)
    assert 1 <= len(tiles) <= 6
    for t in tiles:
        assert Path(t["path"]).exists()
        assert len(t["bbox"]) == 4 and all(isinstance(v, float) for v in t["bbox"])


def test_homography_is_3x3_floats_json_serializable(blank_frame):
    try:
        H = pg.calibrate(blank_frame)
    except pg.CalibrationError:
        pytest.skip("real calibrate refuses a blank frame (expected after Step 2)")
    assert len(H) == 3 and all(len(r) == 3 for r in H)
    json.dumps(H)
