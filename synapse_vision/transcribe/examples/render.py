"""Deterministic synthetic 'handwriting' crops for the few-shot bank.

Synthetic until Henry's real crops exist (see NOTES_T3). Each example is a token list:
    ("t", "text")            baseline text
    ("sup", "2")             superscript
    ("frac", "num", "den")   stacked fraction
    ("strike",)              strike the whole line through
Run:  python -m transcribe.examples.render   -> writes ex_*.png next to this file.
"""
from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
FONT = cv2.FONT_HERSHEY_SCRIPT_SIMPLEX
INK = (28, 28, 40)
SCALE = 1.6
THICK = 2
H = 150


def _text_width(s: str, scale: float = SCALE, thick: int = THICK) -> int:
    (w, _), _ = cv2.getTextSize(s, FONT, scale, thick)
    return w


def _put(img, s: str, x: int, y: int, scale: float = SCALE, thick: int = THICK) -> int:
    cv2.putText(img, s, (x, y), FONT, scale, INK, thick, cv2.LINE_AA)
    return x + _text_width(s, scale, thick) + 6


def _split_sup(s: str) -> tuple[str, str, str]:
    """'x^2 + 1' -> ('x', '2', ' + 1'): only the first character after '^' is raised."""
    base, _, rest = s.partition("^")
    return base, rest[:1], rest[1:]


def _sup_width(s: str) -> int:
    base, sup, tail = _split_sup(s)
    return _text_width(base, 1.1) + (_text_width(sup, 0.7) + 4 if sup else 0) + (_text_width(tail, 1.1) if tail else 0)


def _put_sup(img, s: str, x: int, y: int) -> None:
    base, sup, tail = _split_sup(s)
    cv2.putText(img, base, (x, y), FONT, 1.1, INK, 2, cv2.LINE_AA)
    x += _text_width(base, 1.1) + 2
    if sup:
        cv2.putText(img, sup, (x, y - 18), FONT, 0.7, INK, 2, cv2.LINE_AA)
        x += _text_width(sup, 0.7) + 4
    if tail:
        cv2.putText(img, tail, (x, y), FONT, 1.1, INK, 2, cv2.LINE_AA)


def render(tokens: list[tuple], seed: int = 0, width: int | None = None) -> np.ndarray:
    rnd = random.Random(seed)
    est = sum(_text_width(t[1]) + 40 for t in tokens if t[0] in ("t", "sup")) + \
        sum(max(_text_width(t[1], 1.0), _text_width(t[2], 1.0)) + 40 for t in tokens if t[0] == "frac")
    w = width or max(220, est + 60)
    img = np.full((H, w, 3), 245, np.uint8)
    img = img + rnd.randint(0, 6) - 3  # paper tint
    img = np.clip(img, 0, 255).astype(np.uint8)
    x, base = 24, 100
    strike = False
    for tok in tokens:
        kind = tok[0]
        jitter = rnd.randint(-4, 4)
        if kind == "t":
            x = _put(img, tok[1], x, base + jitter)
        elif kind == "sup":
            x = _put(img, tok[1], x - 4, base - 34 + jitter, scale=1.0, thick=2)
        elif kind == "frac":
            num, den = tok[1], tok[2]
            wn, wd = _sup_width(num), _sup_width(den)
            fw = max(wn, wd) + 10
            _put_sup(img, num, x + (fw - wn) // 2, base - 26 + jitter)
            cv2.line(img, (x, base - 12 + jitter), (x + fw, base - 10 + jitter), INK, 2, cv2.LINE_AA)
            _put_sup(img, den, x + (fw - wd) // 2, base + 34 + jitter)
            x += fw + 10
        elif kind == "strike":
            strike = True
    if strike:
        y0 = base - 20 + rnd.randint(-3, 3)
        cv2.line(img, (14, y0 + 4), (x + 4, y0 - 6), INK, 3, cv2.LINE_AA)
    # slight rotation like a real crop
    ang = rnd.uniform(-1.5, 1.5)
    m = cv2.getRotationMatrix2D((w / 2, H / 2), ang, 1.0)
    img = cv2.warpAffine(img, m, (w, H), borderValue=(245, 245, 245))
    noise = np.random.RandomState(seed).normal(0, 3, img.shape).astype(np.int16)
    return np.clip(img.astype(np.int16) + noise, 0, 255).astype(np.uint8)


EXAMPLES: dict[str, list[tuple]] = {
    "ex_product_rule_mistake": [("frac", "d", "dx"), ("t", "x"), ("sup", "2"), ("t", "sin x = 2x cos x")],
    "ex_distribution_mistake": [("t", "(x+3)"), ("sup", "2"), ("t", "= x"), ("sup", "2"), ("t", "+ 9")],
    "ex_chain_rule_mistake": [("frac", "d", "dx"), ("t", "sin(x"), ("sup", "2"), ("t", ") = cos(x"), ("sup", "2"), ("t", ")")],
    "ex_crossed_out": [("t", "= 2 cos x"), ("strike",)],
    "ex_ambiguous_1_l": [("t", "2l + 1 = 7")],
    "ex_fraction": [("t", "y ="), ("frac", "x^2 + 1", "2x")],  # '^' in a frac part = superscript
    "ex_text_line": [("t", "Find f'(x) if f(x) = x"), ("sup", "2"), ("t", "sin x")],
    "ex_blank": [],
}


def render_all(out_dir: Path = HERE) -> list[Path]:
    paths = []
    for i, (name, tokens) in enumerate(EXAMPLES.items()):
        img = render(tokens, seed=i, width=420 if not tokens else None)
        p = out_dir / f"{name}.png"
        cv2.imwrite(str(p), img)
        paths.append(p)
    return paths


if __name__ == "__main__":
    for p in render_all():
        print(p)
