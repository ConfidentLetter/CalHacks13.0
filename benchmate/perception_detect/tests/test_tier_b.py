"""Step 4: Tier B plumbing with a fake detector (no model, no network)."""
import numpy as np
import pytest

import perception_detect.components as comps_mod
from perception_detect.boxes import iou, nms, to_original
from perception_detect.geometry_bridge import IDENTITY, hole_to_pixel, pitch_px
from perception_detect.owl import Detection
from perception_detect.schema import validate_twin
from perception_detect.tier_b import anchor_pins, detect_boxes, merge_tiers, tier_b_components

H = IDENTITY


def box_over_holes(first: str, last: str, pad_pitches: float = 1.0):
    """[x, y, w, h] covering a pin row from `first` to `last`, padded (like a module body)."""
    (x0, y0), (x1, y1) = hole_to_pixel(first, H), hole_to_pixel(last, H)
    p = pitch_px(H) * pad_pitches
    return (min(x0, x1) - p, min(y0, y1) - p, abs(x1 - x0) + 2 * p, abs(y1 - y0) + 2 * p)


def test_iou_and_nms():
    a, b, c = (0, 0, 10, 10), (5, 0, 10, 10), (100, 100, 10, 10)
    assert iou(a, a) == 1.0 and 0.3 < iou(a, b) < 0.4 and iou(a, c) == 0.0
    kept = nms([Detection(a, 0.5, "x"), Detection(b, 0.9, "y"), Detection(c, 0.4, "x")], 0.3)
    assert [(d.score, d.label) for d in kept] == [(0.9, "y"), (0.4, "x")]


def test_to_original_undoes_tile_offset_and_scale():
    d = to_original(Detection((20, 40, 100, 60), 0.7, "q"), {"bbox": [500, 300, 0, 0], "scale": 2.0})
    assert d.bbox == (510, 320, 50, 30)


def test_detect_boxes_drops_breadboard_and_huge_boxes(tmp_path):
    tiles = [{"path": "t1", "bbox": [0, 0, 1000, 1000], "scale": 1.0},
             {"path": "t2", "bbox": [1000, 0, 1000, 1000], "scale": 1.0}]
    def det(path):
        if path == "t1":
            return [Detection((10, 10, 990, 990), 0.9, "a breadboard"),
                    Detection((0, 0, 1000, 1000), 0.9, "a microcontroller development board"),
                    Detection((100, 100, 50, 50), 0.3, "a small electronic sensor breakout board")]
        raise RuntimeError("tile 2 broke")
    out = detect_boxes("f.jpg", tiles, det, frame_size=(1000, 1000))
    assert [(d.bbox, d.label) for d in out] == [((100, 100, 50, 50), "a small electronic sensor breakout board")]


def test_anchor_pins_bme280_from_box():
    bme_rows = [{"pins": ["VIN", "GND", "SCL", "SDA"], "axis": "number"}]
    # the sensor's pin row sits on the box edge nearest the centre channel: row B is above E/F
    # so the box must extend upwards (away from the channel) and its bottom edge holds the pins
    (x0, y0) = hole_to_pixel("B40", H)
    (x1, _) = hole_to_pixel("B43", H)
    p = pitch_px(H)
    box = (x0 - 0.5 * p, y0 - 3 * p, (x1 - x0) + p, 3.5 * p)
    pins = anchor_pins(box, bme_rows, H)
    assert [(q["name"], q["hole"]) for q in pins] == [("VIN", "B40"), ("GND", "B41"), ("SCL", "B42"), ("SDA", "B43")]


def test_anchor_pins_off_board_is_none():
    rows = [{"pins": ["A", "B", "C", "D"], "axis": "number"}]
    assert anchor_pins((-5000, -5000, 50, 50), rows, H) is None


def test_tier_b_components_reads_label_and_lays_out_pins(tmp_path):
    (x0, y0) = hole_to_pixel("B40", H)
    (x1, _) = hole_to_pixel("B43", H)
    p = pitch_px(H)
    box = (x0 - 0.5 * p, y0 - 3 * p, (x1 - x0) + p, 3.5 * p)
    det = lambda path: [Detection(box, 0.66, "a small electronic sensor breakout board"),
                        Detection((5, 5, 40, 40), 0.5, "a small electronic sensor breakout board")]
    reads = {}
    def reader(frame, bbox):
        reads[tuple(bbox)] = True
        return {"text": "GY-BME280", "legible": True} if bbox[2] > 60 else None
    comps, needs = tier_b_components("f.jpg", None, H, detector=det, reader=reader)
    assert len(reads) == 2
    assert [c["id"] for c in comps] == ["bme280_1", "part_1"]
    assert comps[0]["part_id"] == "bme280" and comps[0]["confidence"] == 0.66
    assert [q["hole"] for q in comps[0]["pins"]] == ["B40", "B41", "B42", "B43"]
    assert comps[1]["part_id"] is None and comps[1]["pins"] == []
    assert [n["element_id"] for n in needs] == ["part_1"]


def test_merge_tiers_prefers_registered():
    a = [{"id": "bme280_1", "part_id": "bme280", "bbox": [0, 0, 100, 100], "pins": [], "confidence": 0.99}]
    b = [{"id": "bme280_1", "part_id": "bme280", "bbox": [500, 500, 10, 10], "pins": [], "confidence": 0.5},
         {"id": "part_1", "part_id": None, "bbox": [10, 10, 80, 80], "pins": [], "confidence": 0.5},
         {"id": "part_2", "part_id": None, "bbox": [900, 900, 50, 50], "pins": [], "confidence": 0.5}]
    assert [c["id"] for c in merge_tiers(a, b)] == ["bme280_1", "part_2"]


def test_detect_components_uses_fake_tier_b(tmp_path, monkeypatch):
    import cv2
    import perception_detect as pd

    frame = tmp_path / "f.jpg"
    cv2.imwrite(str(frame), np.full((600, 800, 3), 150, np.uint8))
    monkeypatch.setenv("BM_TIER_B", "1")
    fake_comp = {"id": "part_1", "part_id": None, "label_text": "", "bbox": [1, 2, 30, 40], "pins": [],
                 "confidence": 0.4, "source": "tier_b"}
    monkeypatch.setattr(comps_mod, "_run_tier_b", lambda *a, **k: [fake_comp])
    pd.register("bme280", 0, hole_to_pixel("B40", H))
    comps = pd.detect_components(str(frame), homography=H)
    assert [c["id"] for c in comps] == ["bme280_1", "part_1"]
    assert validate_twin({**pd.twin.mock_twin("x"), "components": comps}) == []


def test_tier_b_skipped_when_weights_missing(monkeypatch):
    from perception_detect import owl
    monkeypatch.setenv("BM_TIER_B", "1")
    monkeypatch.setattr(owl, "weights_cached", lambda *a, **k: False)
    info = {}
    assert comps_mod._run_tier_b("f.jpg", None, H, info) == []
    assert "weights not cached" in info["tier_b"]
    monkeypatch.setenv("BM_TIER_B", "0")
    info = {}
    assert comps_mod._run_tier_b("f.jpg", None, H, info) == [] and info["tier_b"] == "disabled"
