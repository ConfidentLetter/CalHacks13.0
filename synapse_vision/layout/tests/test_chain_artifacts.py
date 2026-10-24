"""Step 6: artefacts seen on T1's dewarped camera photos and on hand-held frames.

Pieces of the printed margin line that survive rule removal, lone specks far from any
writing, and whole undewarped camera frames (T1 ``no_page``) must not become lines.
A short bold word struck once (letters touching, one crossing run) must still count.
"""
from __future__ import annotations

import random

import cv2
import numpy as np

from layout import segment
from layout._compat import config_get
from layout.classical import detect_lines
from layout.geometry import iou
from layout.segment import is_raw_photo
from layout.tests.synth import PAGE_H, PAGE_W, PEN_BGR, _paste_ink, _render_line_mask, render_page, strike_through
from layout.tests.test_crossed_out import _crop_conf
from layout.tests.test_segment_synth import IOU_MATCH

MIN_CONF = float(config_get("layout.crossed_out_min_conf", 0.6))
RULE_REMNANT_BGR = (95, 95, 95)
RULE_X = 126  # where the chain photos left the printed margin line


def _matched(page, img) -> tuple[int, int]:
    _, specs = detect_lines(img)
    return sum(any(iou(s["bbox"], l.bbox) >= IOU_MATCH for s in specs) for l in page.lines), len(specs)


def test_margin_rule_remnants_are_not_lines():
    page = render_page(5, ruled=False, margin_note=False)
    img = page.image.copy()
    rng = random.Random(5)
    for yy in range(80, PAGE_H - 60, 142):  # one broken piece per rule crossing, tall and short mixed
        h = rng.choice([3, 9, 13, 23, 28, 52, 106])
        cv2.rectangle(img, (RULE_X, yy), (RULE_X + rng.choice([8, 10, 12]), yy + h), RULE_REMNANT_BGR, -1)
    assert _matched(page, img) == (len(page.lines), len(page.lines))


def test_lone_specks_far_from_writing_are_not_lines():
    page = render_page(6, ruled=False, margin_note=False, n_lines=3)
    img = page.image.copy()
    for i, (xx, yy) in enumerate([(300, 1500), (900, 1650), (1300, 1800), (500, 1950), (1100, 2050)]):
        cv2.rectangle(img, (xx, yy), (xx + 8 + i, yy + 11), PEN_BGR, -1)
    assert _matched(page, img) == (len(page.lines), len(page.lines))


def test_undewarped_camera_frame_yields_no_lines(tmp_path):
    """T1 passes the raw frame through on no_page; a frame far larger than its output is skipped."""
    frame = np.full((3024, 4032, 3), 180, dtype=np.uint8)
    cv2.putText(frame, "f(x) = 2x", (900, 1500), cv2.FONT_HERSHEY_SIMPLEX, 6, PEN_BGR, 12)
    raw = tmp_path / "frame.jpg"
    cv2.imwrite(str(raw), frame)
    assert is_raw_photo(str(raw))
    assert segment(str(raw)) == {"regions": [], "lines": []}
    webcam = tmp_path / "webcam.jpg"
    cv2.imwrite(str(webcam), frame[:1080, :1920])
    assert is_raw_photo(str(webcam))
    dewarped = tmp_path / "page.png"
    cv2.imwrite(str(dewarped), render_page(7, ruled=False).image)
    assert not is_raw_photo(str(dewarped)) and (PAGE_W, PAGE_H) == (1700, 2200)
    flat_landscape = tmp_path / "flat.png"  # T1 'flat' upload keeps landscape orientation, long side 2200
    cv2.imwrite(str(flat_landscape), np.full((PAGE_W, PAGE_H, 3), 250, dtype=np.uint8))
    assert not is_raw_photo(str(flat_landscape))


def test_short_bold_word_struck_once_is_detected(tmp_path):
    rng = random.Random(3)
    page = np.full((300, 900, 3), 250, dtype=np.uint8)
    mask = _render_line_mask(["=", "2cosx"], cv2.FONT_HERSHEY_SIMPLEX, 1.4, 18, rng, 700)  # letters fuse into one blob
    bbox = _paste_ink(page, mask, 100, 100, PEN_BGR)
    bbox = strike_through(page, bbox, "single", PEN_BGR, rng, thick=14)  # the strike crosses that blob once
    conf = _crop_conf(page, bbox, tmp_path / "bold.png")
    assert conf >= MIN_CONF, f"bold single strike scored {conf}"
