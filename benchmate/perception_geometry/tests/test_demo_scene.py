"""End-to-end on synthetic renderings of the three mock circuits (ESP32 + BME280 + 6 wires).

What matters for the demo: no CONFIDENT wrong wire (T3 turns confidence < 0.6 into a user question),
most wires confident and right, and the nets built from confident wires agree with the mock nets.
Some seeds route two wires over each other at their ends; that end is unknowable and must come back
with low confidence rather than a wrong hole.
"""
import cv2
import pytest

from perception_geometry import build_nets, calibrate, calibration, detect_wires
from perception_geometry.tests.synth import render_mock_scene

CONFIDENT = 0.6


@pytest.fixture(autouse=True)
def _fresh(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path / "runtime"))
    calibration.clear_cache()
    yield
    calibration.clear_cache()


@pytest.mark.parametrize("name", ["twin_ok", "twin_sda_swapped", "twin_5v"])
@pytest.mark.parametrize("seed", [0, 1])
def test_mock_scene(tmp_path, mock_twins, name, seed):
    twin = mock_twins[name]
    r = render_mock_scene(twin, seed=seed)
    path = tmp_path / f"{name}_{seed}.jpg"
    cv2.imwrite(str(path), r.image, [cv2.IMWRITE_JPEG_QUALITY, 92])
    H = calibrate(str(path))
    wires = detect_wires(str(path), H, [c["bbox"] for c in r.components])
    truth = {frozenset([w.hole_a, w.hole_b]) for w in r.wires}
    confident = [w for w in wires if w["confidence"] >= CONFIDENT]
    desc = [(w["color"], w["end_a"]["hole"], w["end_b"]["hole"], w["confidence"]) for w in wires]

    wrong_confident = [w for w in confident if frozenset([w["end_a"]["hole"], w["end_b"]["hole"]]) not in truth]
    assert not wrong_confident, f"confident but wrong: {wrong_confident}; all: {desc}"
    right_confident = {frozenset([w["end_a"]["hole"], w["end_b"]["hole"]]) for w in confident} & truth
    assert len(right_confident) >= 0.6 * len(truth), f"only {len(right_confident)}/{len(truth)} confident+right: {desc}"

    nets = build_nets(twin["components"], confident)
    want = {tuple(n["members"]) for n in twin["nets"]}
    for net in nets:
        members = tuple(net["members"])
        # a net from confident wires must be a mock net, or a sub-net of one (a low-confidence wire missing)
        assert members in want or any(set(members) < set(w) for w in want), f"spurious net {members}; wires {desc}"
