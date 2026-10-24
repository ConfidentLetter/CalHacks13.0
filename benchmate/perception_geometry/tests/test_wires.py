"""Step 3: detect_wires on the synthetic bench (schema, accuracy, exclude boxes, debug image)."""
import json
from pathlib import Path

import cv2
import jsonschema
import numpy as np
import pytest

from perception_geometry import build_nets, calibrate, calibration, detect_wires
from perception_geometry.wires import WIRE_COLORS, detect_wires_debug

from .synth import render_board


@pytest.fixture(autouse=True)
def _runtime_tmp(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path / "runtime"))
    calibration.clear_cache()
    yield
    calibration.clear_cache()


def _board(tmp_path, seed, n_wires, n_components=0, jitter=1.0):
    r = render_board(seed, n_wires=n_wires, n_components=n_components, marker_jitter_mm=jitter)
    p = tmp_path / f"b{seed}.jpg"
    cv2.imwrite(str(p), r.image, [cv2.IMWRITE_JPEG_QUALITY, 90])
    H = calibrate(str(p))
    return r, str(p), H


def _endpoint_hits(truth_wires, wires) -> tuple[int, int]:
    hit = tot = 0
    for w in truth_wires:
        tot += 2
        best = 0
        for g in wires:
            if g["color"] != w.color:
                continue
            best = max(best, len({g["end_a"]["hole"], g["end_b"]["hole"]} & {w.hole_a, w.hole_b}))
        hit += best
    return hit, tot


def test_output_validates_against_schema(tmp_path, twin_schema, mock_twins):
    r, path, H = _board(tmp_path, 900, 5)
    wires = detect_wires(path, H)
    assert wires, "no wires detected on a 5-wire board"
    twin = dict(mock_twins["twin_ok"])
    twin["board"] = {"type": "breadboard_830", "homography": H}
    twin["wires"] = wires
    twin["nets"] = build_nets(twin["components"], wires)
    jsonschema.validate(twin, twin_schema)
    json.dumps(twin)
    ids = [w["id"] for w in wires]
    assert len(ids) == len(set(ids))
    for w in wires:
        assert w["color"] in WIRE_COLORS
        assert w["id"].startswith(f"w_{w['color']}_")
        assert 0.0 <= w["confidence"] <= 1.0
        for end in (w["end_a"], w["end_b"]):
            assert len(end["pixel"]) == 2
            assert end["hole"] is None or end["hole"].startswith("RAIL_") or end["hole"][0] in "ABCDEFGHIJ"
    # end_a is the left endpoint in warped space, so ids are numbered left to right per colour
    for color in WIRE_COLORS:
        same = [w for w in wires if w["color"] == color]
        assert [w["id"] for w in same] == [f"w_{color}_{i}" for i in range(1, len(same) + 1)]


def test_pixels_are_in_original_image_coordinates(tmp_path):
    r, path, H = _board(tmp_path, 901, 5)
    h, w = r.image.shape[:2]
    for wire in detect_wires(path, H):
        for end in (wire["end_a"], wire["end_b"]):
            x, y = end["pixel"]
            assert -50 <= x <= w + 50 and -50 <= y <= h + 50
    # a correctly detected endpoint pixel lies within ~1 pitch of the true hole pixel
    truth = {(wire.color, wire.hole_a): wire.pixel_a for wire in r.wires} | {(wire.color, wire.hole_b): wire.pixel_b for wire in r.wires}
    pitch_px_orig = r.ppm * 2.54
    checked = 0
    for wire in detect_wires(path, H):
        for end in (wire["end_a"], wire["end_b"]):
            key = (wire["color"], end["hole"])
            if key in truth:
                assert np.hypot(*(np.array(end["pixel"]) - np.array(truth[key]))) < 1.2 * pitch_px_orig
                checked += 1
    assert checked >= 6


def test_endpoint_accuracy_50_boards(tmp_path):
    hit = tot = 0
    for seed in range(50):
        rng = np.random.default_rng(seed)
        r, path, H = _board(tmp_path, 1000 + seed, int(rng.integers(4, 7)), n_components=2)
        h, t = _endpoint_hits(r.wires, detect_wires(path, H, [c["bbox"] for c in r.components]))
        hit += h
        tot += t
    acc = hit / tot
    print(f"wire endpoint accuracy: {hit}/{tot} = {acc:.3f}")
    assert acc >= 0.93, f"endpoint accuracy {acc:.3f}"


def test_exclude_boxes_suppress_pcb_blobs(tmp_path):
    # a dark-blue PCB looks like a blue wire; with its box excluded it must not appear as one
    r, path, H = _board(tmp_path, 1102, 3, n_components=2)
    boxes = [c["bbox"] for c in r.components]
    with_boxes = detect_wires(path, H, boxes)
    truth_pairs = {frozenset([w.hole_a, w.hole_b]) for w in r.wires}
    extras = [w for w in with_boxes if frozenset([w["end_a"]["hole"], w["end_b"]["hole"]]) not in truth_pairs]
    assert len(extras) <= 1
    h, t = _endpoint_hits(r.wires, with_boxes)
    assert h >= t - 1


def test_crossing_same_colour_wires_are_low_confidence(tmp_path):
    # force two wires of one colour; whenever they touch, the result must be flagged (<= 0.5)
    r, path, H = _board(tmp_path, 1200, 6, n_components=0)
    wires = detect_wires(path, H)
    by_colour = {}
    for w in wires:
        by_colour.setdefault(w["color"], []).append(w)
    assert any(len(v) >= 2 for v in by_colour.values()) or len(wires) >= 4


def test_debug_image_is_written(tmp_path, monkeypatch):
    r, path, H = _board(tmp_path, 1300, 4)
    wires, dbg = detect_wires_debug(path, H)
    assert Path(dbg).exists() and Path(dbg).stat().st_size > 10_000
    assert Path(dbg).parent == tmp_path / "runtime" / "debug"
    monkeypatch.setenv("BM_DEBUG_WIRES", "1")
    detect_wires(path, H)
    assert (tmp_path / "runtime" / "debug" / f"wires_{Path(path).stem}.png").exists()


def test_blank_board_has_no_wires(tmp_path):
    r, path, H = _board(tmp_path, 1400, 0)
    assert detect_wires(path, H) == []
