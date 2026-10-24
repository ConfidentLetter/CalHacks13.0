"""Synthetic flat (already dewarped) handwriting-style pages with ground truth.

Each page has 4–12 lines of text/math in OpenCV script fonts: uneven baselines
(line rotated ±3°, words jittered ±6 px), superscripts, stacked fractions
(numerator / bar / denominator — the classic line-splitting trap), one or two
lines struck through (single, double or zig-zag stroke) and sometimes a margin
note.  Ground truth = line boxes, reading order and crossed-out flags.

Usage:
    page = render_page(seed=3)
    page.image          # BGR uint8 (H, W, 3)
    page.lines          # [{bbox, order, crossed_out, kind, region}] in reading order
    page.save(dir)      # writes <dir>/page_<seed>.png and .json
"""
from __future__ import annotations

import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import cv2
import numpy as np

PAGE_W, PAGE_H = 1700, 2200
MARGIN_LEFT, MARGIN_TOP, MARGIN_RIGHT = 160, 180, 160
MAIN_COL_RIGHT = PAGE_W - 420  # leave room for margin notes
FONTS = (cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, cv2.FONT_HERSHEY_SCRIPT_COMPLEX)
PEN_BGR = (35, 30, 40)
PENCIL_BGR = (105, 100, 100)
RULE_BGR = (205, 205, 215)
MARGIN_RULE_BGR = (190, 170, 230)
MAX_LINE_ROT_DEG = 3.0
WORD_JITTER_PX = 6
INK_LUMA_MAX = 160  # pixels darker than this count as ink for ground-truth boxes

WORDS = ["find", "the", "derivative", "of", "so", "then", "let", "we", "get", "by", "product", "rule",
         "chain", "sin", "cos", "tan", "ln", "lim", "dx", "dy", "and", "since", "thus", "where", "u", "v"]
MATH = ["f(x)=x^2 sin x", "f'(x)=2x cos x", "= 2x sin x + x^2 cos x", "g'(x) = 3x^2 - 4x + 1",
        "y = e^x cos x", "dy/dx = -2 sin 2x", "= 0", "x = 3", "f'(0) = 2*0*cos 0 = 0", "u = x^2, v = sin x",
        "(uv)' = u'v + uv'", "= 6x - 4", "lim x->0 sin x / x = 1", "h(t) = t^3 + 2t"]
PROBLEM_PREFIXES = ["Find f'(x) if", "Compute", "Q1.", "3)", "Prove that", "Differentiate"]
MARGIN_NOTES = ["check sign", "why?", "redo", "product rule!", "units", "ok"]


@dataclass
class GTLine:
    bbox: list[int]
    order: int
    crossed_out: bool
    kind: str  # 'text' | 'math' | 'mixed'
    region: str  # 'problem' | 'work' | 'margin'

    def as_dict(self) -> dict:
        return {"bbox": self.bbox, "order": self.order, "crossed_out": self.crossed_out, "kind": self.kind, "region": self.region}


@dataclass
class SynthPage:
    seed: int
    image: np.ndarray
    lines: list[GTLine] = field(default_factory=list)
    ruled: bool = False
    pencil: bool = False

    def save(self, out_dir: str | Path) -> tuple[Path, Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        img_path = out_dir / f"page_{self.seed:03d}.png"
        gt_path = out_dir / f"page_{self.seed:03d}.json"
        cv2.imwrite(str(img_path), self.image)
        gt_path.write_text(json.dumps({"seed": self.seed, "ruled": self.ruled, "pencil": self.pencil,
                                       "lines": [l.as_dict() for l in self.lines]}, indent=1))
        return img_path, gt_path


# --------------------------------------------------------------------------- tokens
def _text_size(text: str, font: int, scale: float, thick: int) -> tuple[int, int, int]:
    (w, h), base = cv2.getTextSize(text, font, scale, thick)
    return w, h, base


def _draw_token(mask: np.ndarray, x: int, baseline: int, token: str, font: int, scale: float, thick: int, rng: random.Random) -> int:
    """Draw one token on the ink mask at (x, baseline); returns the advance in px.

    Token grammar: ``a^b`` -> superscript, ``a/b`` (single slash, no spaces) -> stacked fraction.
    """
    jitter = rng.randint(-WORD_JITTER_PX, WORD_JITTER_PX)
    y = baseline + jitter
    if "^" in token and not token.startswith("^"):
        base, sup = token.split("^", 1)
        bw, bh, _ = _text_size(base, font, scale, thick)
        cv2.putText(mask, base, (x, y), font, scale, 255, thick, cv2.LINE_AA)
        sup_scale = scale * 0.6
        sw, sh, _ = _text_size(sup, font, sup_scale, max(1, thick - 1))
        cv2.putText(mask, sup, (x + bw + 2, y - int(bh * 0.55)), font, sup_scale, 255, max(1, thick - 1), cv2.LINE_AA)
        return bw + sw + 8
    if token.count("/") == 1 and " " not in token and len(token) > 2:
        num, den = token.split("/")
        fs = scale * 0.8
        nw, nh, _ = _text_size(num, font, fs, thick)
        dw, dh, _ = _text_size(den, font, fs, thick)
        w = max(nw, dw) + 10
        bar_y = y - int(nh * 0.45)
        cv2.putText(mask, num, (x + (w - nw) // 2, bar_y - 8), font, fs, 255, thick, cv2.LINE_AA)
        cv2.line(mask, (x, bar_y), (x + w, bar_y), 255, thick)
        cv2.putText(mask, den, (x + (w - dw) // 2, bar_y + dh + 10), font, fs, 255, thick, cv2.LINE_AA)
        return w + 10
    tw, th, _ = _text_size(token, font, scale, thick)
    cv2.putText(mask, token, (x, y), font, scale, 255, thick, cv2.LINE_AA)
    return tw + int(12 * scale)


def _render_line_mask(tokens: Sequence[str], font: int, scale: float, thick: int, rng: random.Random, max_width: int) -> np.ndarray:
    """Render tokens onto a generous canvas, rotate ±3°, return the tight ink mask."""
    canvas = np.zeros((420, max_width + 400, 1), dtype=np.uint8)
    x, baseline = 120, 260
    for tok in tokens:
        if x > max_width - 60:
            break
        x += _draw_token(canvas, x, baseline, tok, font, scale, thick, rng)
    angle = rng.uniform(-MAX_LINE_ROT_DEG, MAX_LINE_ROT_DEG)
    h, w = canvas.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    rotated = cv2.warpAffine(canvas, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=0)
    ys, xs = np.where(rotated > 40)
    if len(xs) == 0:
        return np.zeros((1, 1), dtype=np.uint8)
    return rotated[ys.min(): ys.max() + 1, xs.min(): xs.max() + 1].copy()


def _paste_ink(page: np.ndarray, mask: np.ndarray, x: int, y: int, color: tuple[int, int, int]) -> list[int] | None:
    """Alpha-blend an ink mask onto the page at (x, y); returns the tight bbox of the pasted ink."""
    h, w = mask.shape[:2]
    H, W = page.shape[:2]
    if y + h > H or x + w > W or x < 0 or y < 0:
        return None
    alpha = (mask.astype(np.float32) / 255.0)[..., None]
    region = page[y: y + h, x: x + w].astype(np.float32)
    page[y: y + h, x: x + w] = (region * (1 - alpha) + np.array(color, np.float32) * alpha).astype(np.uint8)
    ys, xs = np.where(mask > 40)
    return [int(x + xs.min()), int(y + ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]


# --------------------------------------------------------------------------- strikes
def strike_through(page: np.ndarray, bbox: Sequence[int], style: str, color: tuple[int, int, int], rng: random.Random, thick: int = 4) -> list[int]:
    """Draw a pen-like strike over ``bbox`` (single | double | zigzag); returns the updated ink bbox."""
    x, y, w, h = bbox
    x0, x1 = x + int(0.03 * w), x + int(0.97 * w)
    cy = y + h // 2
    tilt = rng.randint(-h // 8, h // 8)
    if style == "single":
        cv2.line(page, (x0, cy - tilt), (x1, cy + tilt), color, thick, cv2.LINE_AA)
    elif style == "double":
        off = max(4, h // 7)
        cv2.line(page, (x0, cy - off - tilt), (x1, cy - off + tilt), color, thick, cv2.LINE_AA)
        cv2.line(page, (x0, cy + off - tilt), (x1, cy + off + tilt), color, thick, cv2.LINE_AA)
    else:  # zigzag
        amp = max(6, int(h * 0.3))
        step = max(12, h // 2)
        pts = [(px, cy + (amp if i % 2 else -amp)) for i, px in enumerate(range(x0, x1 + 1, step))]
        cv2.polylines(page, [np.array(pts, np.int32)], False, color, max(2, thick - 1), cv2.LINE_AA)
    return [min(x, x0), min(y, cy - h // 2 - h // 8), max(w, x1 - min(x, x0)), h + h // 4]


# --------------------------------------------------------------------------- pages
def _draw_rules(page: np.ndarray, pitch: int) -> None:
    for yy in range(MARGIN_TOP, PAGE_H - 80, pitch):
        cv2.line(page, (40, yy), (PAGE_W - 40, yy), RULE_BGR, 2)
    cv2.line(page, (MARGIN_LEFT - 50, 40), (MARGIN_LEFT - 50, PAGE_H - 40), MARGIN_RULE_BGR, 3)


def _random_line_tokens(rng: random.Random, kind: str) -> list[str]:
    if kind == "text":
        return rng.sample(WORDS, rng.randint(3, 7))
    expr = rng.choice(MATH).split(" ")
    if rng.random() < 0.45:  # inject a stacked fraction
        expr.insert(rng.randint(0, len(expr)), rng.choice(["x^2/2", "1/x", "dy/dx", "sin x/x", "(x+1)/(x-1)"]))
    return expr


def render_page(seed: int, n_lines: int | None = None, ruled: bool | None = None, pencil: bool | None = None,
                n_crossed: int | None = None, margin_note: bool | None = None) -> SynthPage:
    rng = random.Random(seed)
    n_lines = n_lines if n_lines is not None else rng.randint(4, 12)
    ruled = ruled if ruled is not None else rng.random() < 0.3
    pencil = pencil if pencil is not None else rng.random() < 0.25
    n_crossed = n_crossed if n_crossed is not None else rng.randint(1, 2)
    margin_note = margin_note if margin_note is not None else rng.random() < 0.4
    color = PENCIL_BGR if pencil else PEN_BGR

    page = np.full((PAGE_H, PAGE_W, 3), 255, dtype=np.uint8)
    page[..., :] = np.clip(page.astype(np.int16) - rng.randint(0, 12), 0, 255).astype(np.uint8)  # paper tone
    base_scale = rng.uniform(1.6, 2.4)
    thick = 3 if pencil else rng.choice([3, 4, 5])
    pitch = int(70 * base_scale)
    if ruled:
        _draw_rules(page, pitch)

    y = MARGIN_TOP
    gt: list[GTLine] = []
    crossed_idx = set(rng.sample(range(1, n_lines), min(n_crossed, max(0, n_lines - 1)))) if n_lines > 1 else set()
    for i in range(n_lines):
        font = rng.choice(FONTS)
        scale = base_scale * rng.uniform(0.85, 1.15)
        if i == 0:
            tokens = [rng.choice(PROBLEM_PREFIXES)] + rng.choice(MATH).split(" ")
            kind, region = "mixed", "problem"
        else:
            kind = "text" if rng.random() < 0.2 else "math"
            region = "work"
            tokens = _random_line_tokens(rng, kind)
        mask = _render_line_mask(tokens, font, scale, thick, rng, MAIN_COL_RIGHT - MARGIN_LEFT)
        x = MARGIN_LEFT + rng.randint(0, 60) + (0 if region == "problem" else rng.choice([0, 0, 40, 90]))
        bbox = _paste_ink(page, mask, x, y, color)
        if bbox is None:
            break
        crossed = i in crossed_idx
        if crossed:
            bbox = strike_through(page, bbox, rng.choice(["single", "double", "zigzag"]), color, rng, thick)
        gt.append(GTLine(bbox=bbox, order=len(gt), crossed_out=crossed, kind=kind, region=region))
        extra_gap = int(pitch * 0.9) if i == 0 else rng.randint(int(pitch * 0.35), int(pitch * 0.75))
        y += mask.shape[0] + extra_gap
        if y > PAGE_H - 300:
            break

    if margin_note and gt:
        note = _render_line_mask([rng.choice(MARGIN_NOTES)], rng.choice(FONTS), base_scale * 0.7, max(2, thick - 1), rng, 360)
        target = rng.choice(gt[1:] or gt)
        mx = MAIN_COL_RIGHT + 100
        my = max(MARGIN_TOP, target.bbox[1] - 10)
        bbox = _paste_ink(page, note, mx, my, color)
        if bbox is not None:
            gt.append(GTLine(bbox=bbox, order=len(gt), crossed_out=False, kind="text", region="margin"))

    return SynthPage(seed=seed, image=page, lines=gt, ruled=ruled, pencil=pencil)


def render_demo_page(seed: int = 0) -> SynthPage:
    """The product-rule demo: problem line, wrong derivative, crossed-out line, next line."""
    rng = random.Random(seed)
    page = np.full((PAGE_H, PAGE_W, 3), 250, dtype=np.uint8)
    specs = [(["Find f'(x) if", "f(x)=x^2", "sin x"], "mixed", "problem", False),
             (["f'(x)=2x", "cos x"], "math", "work", False),
             (["= 2 cos x"], "math", "work", True),
             (["f'(0)=2*0*cos 0=0"], "math", "work", False)]
    y, gt = 200, []
    for tokens, kind, region, crossed in specs:
        mask = _render_line_mask(tokens, cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, 2.4, 4, rng, 1200)
        bbox = _paste_ink(page, mask, 170, y, PEN_BGR)
        if crossed:
            bbox = strike_through(page, bbox, "single", PEN_BGR, rng)
        gt.append(GTLine(bbox=bbox, order=len(gt), crossed_out=crossed, kind=kind, region=region))
        y += mask.shape[0] + (110 if region == "problem" else 70)
    return SynthPage(seed=seed, image=page, lines=gt)


def make_testset(out_dir: str | Path, n_pages: int = 20, start_seed: int = 1) -> list[tuple[Path, Path]]:
    return [render_page(seed).save(out_dir) for seed in range(start_seed, start_seed + n_pages)]


if __name__ == "__main__":  # python layout/tests/synth.py runtime/debug/synth
    import sys

    out = sys.argv[1] if len(sys.argv) > 1 else "runtime/debug/synth"
    paths = make_testset(out, n_pages=6)
    render_demo_page().save(out)
    print("\n".join(str(p[0]) for p in paths))
