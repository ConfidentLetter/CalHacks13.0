"""Step 3/4 — detection accuracy, quality flags, dewarp outputs, tiling, all on the synthetic bench."""
from __future__ import annotations

import json

import cv2
import numpy as np
import pytest

from capture import quality as Q
from capture.compat import REPO_ROOT
from capture.detect import detect_page, find_aruco_mat, order_corners, quad_angles_deg, rectangularity
from capture.dewarp import choose_aspect, dewarp, LETTER_ASPECT
from capture.page import detect_and_dewarp
from capture.tests import synth
from capture.tiling import plan_cuts, tile

N_BENCH = 100
CORNER_TOLERANCE = 0.015
BENCH_PASS_RATE = 0.95
BLUR_THRESHOLD_FOR_TESTS = 1500   # see NOTES_T1.md: ask Henry to set page.blur_threshold to this


def _flags(out: dict) -> set[str]:
    return set(out["quality"]["issues"])


def _run(tmp_path, seed: int, **kw) -> tuple[dict, synth.SynthSample]:
    sample = synth.render(seed, **kw)
    path = synth.save(sample, tmp_path / f"s{seed}_{'_'.join(kw) or 'clean'}.jpg")
    return detect_and_dewarp(str(path)), sample


# ----------------------------------------------------------------------------- detection accuracy

def test_corner_accuracy_on_100_synthetic_photos():
    errors = []
    for seed in range(N_BENCH):
        s = synth.render(seed)
        det = detect_page(s.image)
        errors.append(1.0 if det.quad is None else synth.corner_error_fraction(det.quad, s.corners))
    errors = np.array(errors)
    pass_rate = float((errors < CORNER_TOLERANCE).mean())
    assert pass_rate >= BENCH_PASS_RATE, f"pass rate {pass_rate:.2f}; worst seeds {np.argsort(errors)[-5:]} {np.sort(errors)[-5:]}"


def test_detection_survives_dark_exposure():
    for seed in range(5):
        s = synth.render(seed, dark=True)
        det = detect_page(s.image)
        assert det.quad is not None and synth.corner_error_fraction(det.quad, s.corners) < CORNER_TOLERANCE


def test_aruco_fallback_finds_page_region_on_white_desk():
    found = 0
    for seed in range(6):
        s = synth.render(seed, aruco=True, weak_edges=True)
        assert find_aruco_mat(s.image) is not None, f"seed {seed}: markers not detected"
        det = detect_page(s.image)
        if det.quad is None:
            continue
        found += 1
        # Either the page itself or the inner-marker region (which contains the page).
        inside = all(cv2.pointPolygonTest(det.quad.astype(np.float32), (float(x), float(y)), False) >= -3 for x, y in s.corners)
        assert inside or synth.corner_error_fraction(det.quad, s.corners) < CORNER_TOLERANCE
    assert found >= 5


def test_no_page_when_only_desk():
    for seed in range(4):
        s = synth.render(seed, no_page=True)
        assert detect_page(s.image).quad is None


# ----------------------------------------------------------------------------- geometry helpers

def test_order_corners_any_input_order():
    quad = np.array([[10, 10], [200, 12], [205, 300], [8, 295]], np.float32)
    for perm in ([0, 1, 2, 3], [2, 0, 3, 1], [3, 2, 1, 0]):
        assert np.allclose(order_corners(quad[perm]), quad)


def test_rectangularity_and_angles():
    square = np.array([[0, 0], [100, 0], [100, 100], [0, 100]], np.float32)
    assert rectangularity(square) > 0.99 and np.allclose(quad_angles_deg(square), 90)
    kite = np.array([[0, 0], [100, 10], [60, 100], [-50, 60]], np.float32)
    assert rectangularity(kite) < 0.9


def test_aspect_snaps_to_letter_under_perspective():
    hits = 0
    for seed in range(20):
        s = synth.render(seed)
        hits += choose_aspect(order_corners(s.corners), (s.image.shape[1], s.image.shape[0])) == LETTER_ASPECT
    assert hits >= 17


# ----------------------------------------------------------------------------- quality flags

def test_clean_photos_pass_the_gate(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "DEFAULTS", {**Q.DEFAULTS, "page.blur_threshold": BLUR_THRESHOLD_FOR_TESTS})
    for seed in range(6):
        out, _ = _run(tmp_path, seed)
        assert out["quality"]["ok"] is True, out["quality"]
        assert not _flags(out) & {"blur", "hand_in_frame", "no_page", "partial_page"}


def test_blur_flag_fires_only_on_blurred_photos(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "DEFAULTS", {**Q.DEFAULTS, "page.blur_threshold": BLUR_THRESHOLD_FOR_TESTS})
    monkeypatch.setattr(Q, "cfg", lambda key, default=None: Q.DEFAULTS.get(key, default))
    sharp = [_run(tmp_path, seed)[0] for seed in range(4)]
    blurred = [_run(tmp_path, seed, blur=True)[0] for seed in range(4)]
    assert all("blur" not in _flags(o) for o in sharp), [o["quality"]["blur_score"] for o in sharp]
    assert all("blur" in _flags(o) and o["quality"]["ok"] is False for o in blurred), [o["quality"]["blur_score"] for o in blurred]
    assert min(o["quality"]["blur_score"] for o in sharp) > max(o["quality"]["blur_score"] for o in blurred)


def test_glare_flag(tmp_path):
    glare = [_run(tmp_path, seed, glare=True)[0] for seed in range(4)]
    clean = [_run(tmp_path, seed)[0] for seed in range(4)]
    assert all("glare" in _flags(o) for o in glare), [o["quality"]["glare_fraction"] for o in glare]
    assert all(o["quality"]["ok"] is True for o in glare), "glare alone is a warning, not a block"
    assert all("glare" not in _flags(o) for o in clean), [o["quality"]["glare_fraction"] for o in clean]


def test_hand_in_frame_blocks(tmp_path):
    outs = [_run(tmp_path, seed, hand=True)[0] for seed in range(6)]
    assert all("hand_in_frame" in _flags(o) and o["quality"]["ok"] is False for o in outs), [o["quality"] for o in outs]


def test_too_dark_is_a_warning(tmp_path):
    out, _ = _run(tmp_path, 1, dark=True)
    assert "too_dark" in _flags(out) and "no_page" not in _flags(out)


def test_no_page_and_partial_page_block(tmp_path):
    out, _ = _run(tmp_path, 2, no_page=True)
    assert out["quality"]["ok"] is False and "no_page" in _flags(out)
    assert out["dewarped_path"].endswith(".jpg") and out["width"] > 0
    blocked = [_run(tmp_path, seed, partial=True)[0] for seed in range(4)]
    assert all(o["quality"]["ok"] is False and _flags(o) & {"partial_page", "no_page"} for o in blocked)


def test_skin_fraction_ignores_red_ink_and_desk():
    s = synth.render(5)
    assert Q.skin_fraction_in_page(s.image, order_corners(s.corners)) < 0.01


# ----------------------------------------------------------------------------- dewarp outputs

def test_dewarped_outputs_written_and_portrait(tmp_path):
    out, sample = _run(tmp_path, 3)
    color = cv2.imread(str(REPO_ROOT / out["dewarped_path"]))
    gray = cv2.imread(str(REPO_ROOT / out["dewarped_gray_path"]), cv2.IMREAD_GRAYSCALE)
    assert color is not None and gray is not None
    assert color.shape[:2] == (out["height"], out["width"]) == gray.shape[:2]
    assert out["height"] > out["width"], "portrait"
    assert out["dewarped_path"].startswith("runtime/dewarped/"), "repo-relative for the viewer"
    h = np.array(out["homography"])
    assert h.shape == (3, 3)
    projected = cv2.perspectiveTransform(order_corners(sample.corners).reshape(1, 4, 2).astype(np.float32), h.astype(np.float32)).reshape(4, 2)
    expected = np.array([[0, 0], [out["width"] - 1, 0], [out["width"] - 1, out["height"] - 1], [0, out["height"] - 1]])
    assert np.abs(projected - expected).max() < 0.02 * out["height"]
    assert (REPO_ROOT / out["debug_path"]).exists()


def test_lighting_is_flattened():
    s = synth.render(4, glare=False)
    dw = dewarp(s.image, order_corners(s.corners))
    paper = dw.gray[dw.gray > 128]
    assert paper.std() < 25, "normalized paper should be nearly uniform"
    assert dw.color.shape[2] == 3


def test_json_serializable(tmp_path):
    out, _ = _run(tmp_path, 6)
    json.dumps(out)


# ----------------------------------------------------------------------------- tiling

def test_plan_cuts_balances_ink_and_avoids_dense_rows():
    profile = np.zeros(2000)
    for y0 in (100, 500, 900, 1300, 1700):
        profile[y0:y0 + 80] = 50.0
    cuts = plan_cuts(profile, max_tiles=4, quiet_search_px=40, min_tile_px=200)
    assert cuts[-1] == 2000 and len(cuts) == 4
    for c in cuts[:-1]:
        assert profile[c] == 0, f"cut {c} goes through ink"
    assert plan_cuts(np.zeros(2000), 6, 40, 200) == [2000]


def test_tile_outputs(tmp_path):
    out, _ = _run(tmp_path, 7, n_lines=7)
    tiles = tile(out["dewarped_path"], max_tiles=4)
    assert 2 <= len(tiles) <= 4
    h, w = out["height"], out["width"]
    for i, t in enumerate(tiles):
        x, y, tw, th = t["bbox"]
        assert x == 0 and tw == w and 0 <= y < h and y + th <= h
        img = cv2.imread(str(REPO_ROOT / t["path"]))
        assert img is not None and img.shape[:2] == (th, tw)
        if i:
            prev = tiles[i - 1]["bbox"]
            assert y < prev[1] + prev[3], "neighbouring tiles overlap"
    assert tiles[0]["bbox"][1] == 0 and tiles[-1]["bbox"][1] + tiles[-1]["bbox"][3] == h
    assert tile("runtime/does_not_exist.jpg") == []


# ----------------------------------------------------------------------------- flat pages (scans, uploads)

def test_flat_demo_scan_is_accepted_whole():
    """T4's eval/testset/synthetic_demo.jpg: already flat, white to every border — must not be 'no_page' or 'glare'."""
    path = REPO_ROOT / "eval" / "testset" / "synthetic_demo.jpg"
    if not path.exists():
        pytest.skip("eval/testset/synthetic_demo.jpg not present")
    out = detect_and_dewarp(str(path))
    assert out["quality"]["ok"] is True and out["quality"]["issues"] == [], out["quality"]
    assert out["quality"]["glare_fraction"] < 0.01
    assert out["detection"]["method"] == "flat"
    assert (out["width"], out["height"]) == (1700, 2200), "same size as the input, so truth bboxes line up"
    assert out["dewarped_path"].startswith("runtime/dewarped/")


def test_flat_synthetic_page_keeps_orientation(tmp_path):
    s = synth.render(5, crossed_out=True)
    portrait = synth.save(synth.SynthSample(s.page, s.corners, s.page), tmp_path / "flat_portrait.jpg")
    out = detect_and_dewarp(str(portrait))
    assert out["quality"]["ok"] and out["detection"]["method"] == "flat" and out["height"] > out["width"]
    landscape_img = cv2.rotate(s.page, cv2.ROTATE_90_CLOCKWISE)
    landscape = synth.save(synth.SynthSample(landscape_img, s.corners, landscape_img), tmp_path / "flat_landscape.jpg")
    out = detect_and_dewarp(str(landscape))
    assert out["quality"]["ok"] and out["detection"]["method"] == "flat" and out["width"] > out["height"]


def test_camera_frames_still_take_the_strict_path(tmp_path):
    for seed in range(4):
        out, _ = _run(tmp_path, seed)
        assert out["detection"]["method"] in ("edges", "threshold")
    out, _ = _run(tmp_path, 1, no_page=True)
    assert out["detection"]["method"] == "none" and "no_page" in _flags(out)


def test_white_paper_is_not_glare_but_a_lamp_blob_is():
    white = np.full((1100, 850), 255, np.uint8)
    assert Q.glare_fraction(white) == 0.0
    paper = np.full((1100, 850), 205, np.uint8)
    cv2.circle(paper, (425, 550), 120, 255, -1)
    assert 0.02 < Q.glare_fraction(paper) < 0.08


# ----------------------------------------------------------------------------- printed ruling (H+5 relay from T2)

def _rule_visibility(gray: np.ndarray, rows: list[int]) -> float:
    paper = cv2.medianBlur(gray, 15)
    inverted = cv2.subtract(paper, gray)
    return float(np.mean([(inverted[max(0, y - 4):y + 5, 300:1400] >= 8).any(axis=0).mean() for y in rows]))


def test_printed_rules_suppressed_in_gray_but_kept_in_color():
    from capture.dewarp import suppress_printed_rules

    s = synth.render(1, ruled=True, n_lines=5)
    dw = dewarp(s.image, order_corners(s.corners))
    ph = s.page.shape[0]
    top, spacing, sy = int(ph * 0.10), int(ph * 0.065), dw.gray.shape[0] / ph
    rule_rows = [int(round(y * sy)) for y in range(top, ph - int(ph * 0.05), spacing)]
    raw = cv2.cvtColor(dw.color, cv2.COLOR_BGR2GRAY)
    assert _rule_visibility(raw, rule_rows) > 0.9, "bench page really has rules"
    assert _rule_visibility(dw.gray, rule_rows) < 0.15, "gray output: rules suppressed"
    margin_x = int((int(s.page.shape[1] * 0.10) - 20) * dw.gray.shape[1] / s.page.shape[1])
    cleaned, _ = suppress_printed_rules(raw)
    assert (cleaned[300:1900, margin_x - 3:margin_x + 4] < 200).mean() < 0.05, "vertical margin line suppressed"


def test_rule_suppression_keeps_handwriting_and_fraction_bars():
    from capture.dewarp import suppress_printed_rules

    s = synth.render(4, ruled=True, n_lines=0)
    page = s.page.copy()
    cv2.putText(page, "f'(x) = 2x cos x", (120, 400), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 1.6, (40, 30, 30), 3, cv2.LINE_AA)
    cv2.line(page, (200, 900), (520, 900), (40, 30, 30), 3)          # a fraction bar / underline, 38 % of the width
    gray = cv2.cvtColor(page, cv2.COLOR_BGR2GRAY)
    cleaned, mask = suppress_printed_rules(gray)
    ink = gray < 120
    assert (mask[ink] > 0).mean() < 0.10, "at most the anti-aliased edges of strokes crossing a rule are touched"
    assert (cleaned[898:903, 250:470] < 150).mean() > 0.5, "fraction bar kept"
    assert mask.sum() > 0, "the rules themselves were found"
