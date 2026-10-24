"""Step 4: strike-through detection on synthetic crops.

Struck lines (single, double, zig-zag) must score >= layout.crossed_out_min_conf; clean lines,
fraction bars and underlines must not. Between 0.4 and the threshold -> 'unsure' (T3 asks the model).
"""
from __future__ import annotations

import inspect
import random
from pathlib import Path

import cv2
import numpy as np
import pytest

from layout import is_crossed_out, segment
from layout._compat import REPO_ROOT, config_get
from layout.crops import write_line_crop
from layout.crossed_out import crossed_out_confidence, _load_ink
from layout.tests.synth import PEN_BGR, _paste_ink, _render_line_mask, render_demo_page, render_page, strike_through

SEEDS = list(range(1, 31))
MIN_CONF = float(config_get("layout.crossed_out_min_conf", 0.6))
UNSURE_MIN = 0.4


def _crop_conf(image: np.ndarray, bbox, path: Path) -> float:
    write_line_crop(image, bbox, path)
    return crossed_out_confidence(_load_ink(str(path)))


@pytest.fixture(scope="module")
def synth_scores(tmp_path_factory) -> list[tuple[bool, float, str]]:
    out = tmp_path_factory.mktemp("crops")
    rows = []
    for seed in SEEDS:
        page = render_page(seed)
        for i, line in enumerate(page.lines):
            rows.append((line.crossed_out, _crop_conf(page.image, line.bbox, out / f"s{seed}_l{i}.png"), f"s{seed}_l{i}"))
    return rows


def test_signature():
    assert str(inspect.signature(is_crossed_out, eval_str=True)) == "(crop_path: str) -> tuple[bool, float]"


def test_struck_lines_detected(synth_scores):
    struck = [(c, name) for crossed, c, name in synth_scores if crossed]
    hit = [name for c, name in struck if c >= MIN_CONF]
    assert len(hit) / len(struck) >= 0.85, f"struck recall {len(hit)}/{len(struck)}; missed {[n for c, n in struck if c < MIN_CONF]}"


def test_clean_lines_never_flagged(synth_scores):
    clean = [(c, name) for crossed, c, name in synth_scores if not crossed]
    false = [name for c, name in clean if c >= MIN_CONF]
    unsure = [name for c, name in clean if UNSURE_MIN <= c < MIN_CONF]
    assert not false, f"clean lines flagged crossed_out: {false}"
    assert len(unsure) / len(clean) <= 0.02, f"too many unsure clean lines: {unsure}"


def _line_image(tokens, rng, width=1400):
    page = np.full((400, width, 3), 250, dtype=np.uint8)
    mask = _render_line_mask(tokens, cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 2.2, 4, rng, width - 300)
    bbox = _paste_ink(page, mask, 120, 120, PEN_BGR)
    return page, bbox


def test_fraction_bar_alone_is_not_a_strike(tmp_path):
    rng = random.Random(0)
    for tokens in (["(x+1)/(x-1)"], ["1/x"], ["dy/dx"], ["x^2/2", "+", "1/x"]):
        page, bbox = _line_image(tokens, rng)
        conf = _crop_conf(page, bbox, tmp_path / "frac.png")
        assert conf < UNSURE_MIN, f"fraction {tokens} scored {conf}"


def test_underline_is_not_a_strike(tmp_path):
    rng = random.Random(1)
    page, bbox = _line_image(["so", "f'(x)", "=", "2x"], rng)
    x, y, w, h = bbox
    cv2.line(page, (x - 10, y + h + 10), (x + w + 10, y + h + 12), PEN_BGR, 4, cv2.LINE_AA)
    conf = _crop_conf(page, [x - 12, y, w + 24, h + 16], tmp_path / "underline.png")
    assert conf < UNSURE_MIN, f"underline scored {conf}"


@pytest.mark.parametrize("style", ["single", "double", "zigzag"])
def test_each_strike_style_detected(style, tmp_path):
    rng = random.Random(2)
    page, bbox = _line_image(["f'(x)", "=", "2x", "cos", "x"], rng)
    bbox = strike_through(page, bbox, style, PEN_BGR, rng)
    conf = _crop_conf(page, bbox, tmp_path / f"{style}.png")
    assert conf >= MIN_CONF, f"{style} strike scored {conf}"


def test_is_crossed_out_respects_config_threshold(tmp_path, monkeypatch):
    rng = random.Random(3)
    page, bbox = _line_image(["=", "2", "cos", "x"], rng)
    bbox = strike_through(page, bbox, "single", PEN_BGR, rng)
    p = tmp_path / "crop.png"
    write_line_crop(page, bbox, p)
    crossed, conf = is_crossed_out(str(p))
    assert crossed and conf >= MIN_CONF
    import layout.crossed_out as co

    monkeypatch.setattr(co, "config_get", lambda k, d=None: 1.01 if k == "layout.crossed_out_min_conf" else d, raising=False)
    monkeypatch.setattr("layout._compat.config_get", lambda k, d=None: 1.01 if k == "layout.crossed_out_min_conf" else d)
    crossed2, conf2 = is_crossed_out(str(p))
    assert conf2 == conf and crossed2 is False


def test_missing_or_blank_crop(tmp_path):
    assert is_crossed_out(str(tmp_path / "nope.png")) == (False, 0.0)
    blank = tmp_path / "blank.png"
    cv2.imwrite(str(blank), np.full((60, 300), 255, dtype=np.uint8))
    assert is_crossed_out(str(blank)) == (False, 0.0)


def test_demo_page_struck_line_gets_crossed_out_hint(tmp_path):
    page = render_demo_page()
    p = tmp_path / "demo_strike.png"
    cv2.imwrite(str(p), page.image)
    hints = [l["status_hint"] for l in segment(str(p))["lines"]]
    assert hints == ["active", "active", "crossed_out", "active"], hints
