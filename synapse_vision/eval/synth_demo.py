"""Synthetic stand-ins for the demo page (product-rule mistake, one struck line) until Henry's photos land.

    python -m eval.synth_demo
writes eval/testset/synthetic_demo.jpg (flat scan, white to the borders — T1's tests rely on it staying flat)
and eval/testset/synthetic_demo_mat.jpg (same page on a dark mat, 2° rotated, exercising T1's quad detector).
Both share the same truth boxes (T1 dewarps both to 1700×2200)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "eval" / "testset" / "synthetic_demo.jpg"          # flat scan, white to every border (T1 'flat' path)
OUT_MAT = ROOT / "eval" / "testset" / "synthetic_demo_mat.jpg"  # same page on a dark mat, 2° rotated (T1 quad path)
LINES = [(130, 160, "Find f'(x) if f(x) = x^2 sin x"), (130, 330, "f'(x) = 2x · cos x"),
         (130, 470, "= 2 cos x"), (130, 610, "f'(0) = 2·0·cos 0 = 0")]
FONT_CANDIDATES = ["/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf", "/System/Library/Fonts/Supplemental/Chalkboard.ttc"]


def _font(size: int) -> ImageFont.ImageFont:
    for f in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            continue
    return ImageFont.load_default()


def page_image(page_wh: tuple[int, int] = (1700, 2200)) -> Image.Image:
    page = Image.new("RGB", page_wh, (250, 249, 245))
    d = ImageDraw.Draw(page)
    font = _font(72)
    for x, y, t in LINES:
        d.text((x, y), t, fill=(25, 25, 35), font=font)
    d.line([(130, 520), (700, 500)], fill=(25, 25, 35), width=6)  # strike-through on line 3
    return page


def build_flat(out: Path = OUT) -> Path:
    out.parent.mkdir(parents=True, exist_ok=True)
    page_image().save(out, quality=92)
    return out


def build(out: Path = OUT_MAT, page_wh: tuple[int, int] = (1700, 2200), frame_wh: tuple[int, int] = (2200, 2800)) -> Path:
    page = page_image(page_wh)
    frame = Image.new("RGB", frame_wh, (48, 46, 50))
    rotated = page.rotate(2.0, expand=True, resample=Image.BICUBIC, fillcolor=(48, 46, 50))
    frame.paste(rotated, ((frame_wh[0] - rotated.width) // 2, (frame_wh[1] - rotated.height) // 2))
    out.parent.mkdir(parents=True, exist_ok=True)
    frame.save(out, quality=92)
    return out


if __name__ == "__main__":
    print("wrote", build_flat(), "and", build())
