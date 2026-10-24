"""Synthetic "photo of a handwritten page" generator — T1's test bench until real photos exist.

render(seed, ...) builds: a white Letter/A4 sheet with script-font text and math (optionally ruled),
optionally on a dark mat with 4 ArUco markers, placed on a textured desk, viewed with random
perspective (±15°) and roll (±10°), uneven lighting + glare blob, slight blur, JPEG compression.
Returns the image plus the ground-truth page corners in frame pixels (TL, TR, BR, BL).

Usage:  python -m capture.tests.synth --n 8 --out runtime/debug/synth
"""
from __future__ import annotations

import argparse
import math
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

LETTER_ASPECT = 11.0 / 8.5
A4_ASPECT = 297.0 / 210.0
INK_COLORS_BGR = ((40, 30, 30), (90, 50, 20), (70, 70, 70), (30, 30, 120))
SAMPLE_LINES = (
    "Find f'(x) if f(x) = x^2 sin x",
    "f'(x) = 2x . cos x",
    "= 2 cos x",
    "f'(0) = 2 . 0 . cos 0 = 0",
    "d/dx (x^3 + 2x) = 3x^2 + 2",
    "int x dx = x^2 / 2 + C",
    "lim x->0 sin x / x = 1",
    "y = mx + b",
    "a^2 + b^2 = c^2",
    "chain rule: g'(h(x)) h'(x)",
)
ARUCO_IDS_TL_TR_BR_BL = (0, 1, 2, 3)


@dataclass
class SynthSample:
    image: np.ndarray                  # BGR frame as the camera would see it
    corners: np.ndarray                # (4, 2) float32 page corners in frame px: TL, TR, BR, BL
    page: np.ndarray                   # the flat page canvas (BGR) before warping
    params: dict = field(default_factory=dict)

    @property
    def diagonal(self) -> float:
        return float(np.linalg.norm(self.corners[0] - self.corners[2]))


# ----------------------------------------------------------------------------- page canvas

def render_page_canvas(rng: np.random.Generator, page_w: int, page_h: int, ruled: bool,
                       n_lines: int, pencil: bool, crossed_out: bool) -> np.ndarray:
    """A flat, top-down page: white paper, optional ruling, script-font handwriting."""
    paper = np.full((page_h, page_w, 3), int(rng.integers(222, 240)), np.uint8)
    paper = paper.astype(np.float32) + rng.normal(0, 3, paper.shape).astype(np.float32)
    paper = np.clip(paper, 0, 255).astype(np.uint8)

    margin_x, top = int(page_w * 0.10), int(page_h * 0.10)
    spacing = int(page_h * 0.065)
    if ruled:
        for y in range(top, page_h - int(page_h * 0.05), spacing):
            cv2.line(paper, (0, y), (page_w, y), (215, 190, 170), 1, cv2.LINE_AA)
        cv2.line(paper, (margin_x - 20, 0), (margin_x - 20, page_h), (200, 170, 220), 2, cv2.LINE_AA)

    ink = (110, 110, 110) if pencil else INK_COLORS_BGR[int(rng.integers(len(INK_COLORS_BGR)))]
    scale = page_w / 850.0 * float(rng.uniform(0.9, 1.3))
    thickness = max(1, int(round(2 * scale))) if not pencil else 1
    y = top + spacing - int(spacing * 0.3)
    for i in range(n_lines):
        text = SAMPLE_LINES[int(rng.integers(len(SAMPLE_LINES)))]
        x = margin_x + int(rng.integers(0, int(page_w * 0.08)))
        cv2.putText(paper, text, (x, y), cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, scale, ink, thickness, cv2.LINE_AA)
        if crossed_out and i == 2:
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SCRIPT_SIMPLEX, scale, thickness)
            cv2.line(paper, (x - 5, y - th // 2 + 3), (x + tw + 5, y - th // 2 - 6), ink, thickness + 1, cv2.LINE_AA)
        y += spacing
        if y > page_h - spacing:
            break
    return paper


def draw_aruco_mat(page: np.ndarray, mat_color: tuple[int, int, int], scale: float = 1.35,
                   marker_px: int | None = None) -> tuple[np.ndarray, np.ndarray]:
    """Place the page centred on a mat with 4 ArUco markers (DICT_4X4_50 ids 0-3 TL,TR,BR,BL) at its corners.
    Returns (mat canvas, page corners inside that canvas)."""
    ph, pw = page.shape[:2]
    mh, mw = int(ph * scale), int(pw * scale)
    mat = np.zeros((mh, mw, 3), np.uint8)
    mat[:] = mat_color
    ox, oy = (mw - pw) // 2, (mh - ph) // 2
    mat[oy:oy + ph, ox:ox + pw] = page
    size = marker_px or max(40, int(min(mw, mh) * 0.08))
    pad = max(6, size // 6)
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    spots = ((pad, pad), (mw - size - pad, pad), (mw - size - pad, mh - size - pad), (pad, mh - size - pad))
    for marker_id, (x, y) in zip(ARUCO_IDS_TL_TR_BR_BL, spots):
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, size)
        border = np.full((size + 2 * pad, size + 2 * pad), 255, np.uint8)
        border[pad:pad + size, pad:pad + size] = marker
        x0, y0 = max(0, x - pad), max(0, y - pad)
        h, w = border.shape
        mat[y0:y0 + h, x0:x0 + w] = cv2.cvtColor(border, cv2.COLOR_GRAY2BGR)[: mh - y0, : mw - x0]
    corners = np.array([[ox, oy], [ox + pw, oy], [ox + pw, oy + ph], [ox, oy + ph]], np.float32)
    return mat, corners


# ----------------------------------------------------------------------------- camera geometry

def _rotation(roll_deg: float, tilt_x_deg: float, tilt_y_deg: float) -> np.ndarray:
    r, tx, ty = (math.radians(v) for v in (roll_deg, tilt_x_deg, tilt_y_deg))
    rz = np.array([[math.cos(r), -math.sin(r), 0], [math.sin(r), math.cos(r), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(tx), -math.sin(tx)], [0, math.sin(tx), math.cos(tx)]])
    ry = np.array([[math.cos(ty), 0, math.sin(ty)], [0, 1, 0], [-math.sin(ty), 0, math.cos(ty)]])
    return rz @ rx @ ry


def project_plane(points_xy: np.ndarray, canvas_wh: tuple[int, int], frame_wh: tuple[int, int],
                  fill: float, roll_deg: float, tilt_x_deg: float, tilt_y_deg: float,
                  shift_xy: tuple[float, float] = (0.0, 0.0)) -> np.ndarray:
    """Pinhole-project points on a flat canvas (pixels) into the camera frame (pixels)."""
    cw, ch = canvas_wh
    fw, fh = frame_wh
    world_scale = fill * fh / ch                      # canvas px -> world units so the canvas fills `fill` of frame height
    pts = (points_xy - np.array([cw / 2.0, ch / 2.0])) * world_scale
    pts3 = np.concatenate([pts, np.zeros((len(pts), 1))], axis=1) @ _rotation(roll_deg, tilt_x_deg, tilt_y_deg).T
    focal = 1.6 * fh                                   # distance of camera; controls perspective strength
    depth = focal + pts3[:, 2]
    u = focal * pts3[:, 0] / depth + fw / 2.0 + shift_xy[0]
    v = focal * pts3[:, 1] / depth + fh / 2.0 + shift_xy[1]
    return np.stack([u, v], axis=1).astype(np.float32)


def _keep_in_frame(page_corners: np.ndarray, canvas_wh: tuple[int, int], frame_wh: tuple[int, int], fill: float,
                   roll: float, tilt_x: float, tilt_y: float, shift: tuple[float, float],
                   margin: float = 0.025) -> tuple[float, tuple[float, float]]:
    """Shrink `fill` and adjust the shift so every page corner stays `margin` of the frame away from its edges."""
    fw, fh = frame_wh
    for _ in range(6):
        pts = project_plane(page_corners, canvas_wh, frame_wh, fill, roll, tilt_x, tilt_y, shift)
        ext_x, ext_y = np.ptp(pts[:, 0]), np.ptp(pts[:, 1])
        if ext_x > fw * (1 - 2 * margin) or ext_y > fh * (1 - 2 * margin):
            fill *= 0.95 * min(fw * (1 - 2 * margin) / ext_x, fh * (1 - 2 * margin) / ext_y)
            continue
        dx = max(0.0, fw * margin - pts[:, 0].min()) - max(0.0, pts[:, 0].max() - fw * (1 - margin))
        dy = max(0.0, fh * margin - pts[:, 1].min()) - max(0.0, pts[:, 1].max() - fh * (1 - margin))
        return fill, (shift[0] + dx, shift[1] + dy)
    return fill, shift


def desk_texture(rng: np.random.Generator, frame_wh: tuple[int, int], base_bgr: tuple[int, int, int]) -> np.ndarray:
    fw, fh = frame_wh
    noise = rng.normal(0, 1, (fh // 8, fw // 8)).astype(np.float32)
    noise = cv2.resize(cv2.GaussianBlur(noise, (0, 0), 2), (fw, fh), interpolation=cv2.INTER_CUBIC)
    grain = rng.normal(0, 4, (fh, fw)).astype(np.float32)
    desk = np.empty((fh, fw, 3), np.float32)
    for c in range(3):
        desk[:, :, c] = base_bgr[c] + 18 * noise + grain
    return np.clip(desk, 0, 255)


def apply_lighting(img: np.ndarray, rng: np.random.Generator, glare_center: tuple[float, float] | None,
                   glare_strength: float, gradient_min: float) -> np.ndarray:
    fh, fw = img.shape[:2]
    yy, xx = np.mgrid[0:fh, 0:fw].astype(np.float32)
    angle = rng.uniform(0, 2 * math.pi)
    ramp = (xx * math.cos(angle) + yy * math.sin(angle))
    ramp = (ramp - ramp.min()) / max(1e-6, ramp.max() - ramp.min())
    gain = gradient_min + (1.0 - gradient_min) * ramp
    out = img.astype(np.float32) * gain[:, :, None]
    if glare_center is not None and glare_strength > 0:
        gx, gy = glare_center
        sigma = 0.08 * max(fw, fh)
        blob = np.exp(-((xx - gx) ** 2 + (yy - gy) ** 2) / (2 * sigma ** 2))
        out += (glare_strength * blob)[:, :, None]
    return np.clip(out, 0, 255)


def draw_hand(img: np.ndarray, rng: np.random.Generator, corners: np.ndarray) -> np.ndarray:
    """A skin-toned hand + dark pen entering from the bottom edge of the page."""
    out = img.copy()
    bl, br = corners[3], corners[2]
    cx, cy = (bl + br) / 2.0
    size = float(np.linalg.norm(br - bl))
    skin = tuple(int(v) for v in (rng.integers(100, 140), rng.integers(140, 175), rng.integers(190, 225)))
    cv2.ellipse(out, (int(cx), int(cy + size * 0.05)), (int(size * 0.22), int(size * 0.30)),
                float(rng.uniform(-20, 20)), 0, 360, skin, -1, cv2.LINE_AA)
    for k in range(4):
        fx = int(cx - size * 0.18 + k * size * 0.11)
        cv2.ellipse(out, (fx, int(cy - size * 0.12)), (int(size * 0.045), int(size * 0.18)), 0, 0, 360, skin, -1, cv2.LINE_AA)
    cv2.line(out, (int(cx), int(cy - size * 0.1)), (int(cx + size * 0.15), int(cy - size * 0.45)), (30, 30, 30), max(3, int(size * 0.012)), cv2.LINE_AA)
    return out


# ----------------------------------------------------------------------------- the generator

def render(seed: int = 0, *, frame_wh: tuple[int, int] = (1600, 1200), page_px_w: int = 850,
           aspect: float = LETTER_ASPECT, fill: float | None = None, ruled: bool | None = None,
           pencil: bool = False, crossed_out: bool = False, n_lines: int | None = None,
           blur: bool = False, glare: bool = False, dark: bool = False, hand: bool = False,
           no_page: bool = False, partial: bool = False, aruco: bool = False, weak_edges: bool = False,
           max_tilt_deg: float = 15.0, max_roll_deg: float = 10.0, jpeg_quality: int | None = None) -> SynthSample:
    """Render one synthetic camera frame. Flags build images that *should* trip a given quality issue."""
    rng = np.random.default_rng(seed)
    page_h = int(round(page_px_w * aspect))
    ruled = bool(rng.random() < 0.4) if ruled is None else ruled
    n_lines = int(rng.integers(3, 8)) if n_lines is None else n_lines
    page = render_page_canvas(rng, page_px_w, page_h, ruled, n_lines, pencil, crossed_out)

    desk_base = (226, 226, 226) if weak_edges else tuple(int(v) for v in rng.integers(35, 95, 3))
    if aruco:
        mat_color = desk_base if weak_edges else (40, 40, 45)
        canvas, page_corners_canvas = draw_aruco_mat(page, mat_color)
    else:
        canvas = page
        page_corners_canvas = np.array([[0, 0], [page_px_w, 0], [page_px_w, page_h], [0, page_h]], np.float32)

    ch, cw = canvas.shape[:2]
    fill = float(rng.uniform(0.70, 0.95)) if fill is None else fill   # sheet + 2-3 cm margin in frame, like the real mount
    roll = float(rng.uniform(-max_roll_deg, max_roll_deg))
    tilt_x, tilt_y = (float(rng.uniform(-max_tilt_deg, max_tilt_deg)) for _ in range(2))
    shift = (float(rng.uniform(-0.05, 0.05)) * frame_wh[0], float(rng.uniform(-0.04, 0.04)) * frame_wh[1])
    if partial:
        shift = (shift[0], frame_wh[1] * 0.45 * (1 if rng.random() < 0.5 else -1))

    canvas_corners = np.array([[0, 0], [cw, 0], [cw, ch], [0, ch]], np.float32)
    if not partial:
        keep = canvas_corners if aruco else page_corners_canvas
        fill, shift = _keep_in_frame(keep, (cw, ch), frame_wh, fill, roll, tilt_x, tilt_y, shift)
    frame_canvas_corners = project_plane(canvas_corners, (cw, ch), frame_wh, fill, roll, tilt_x, tilt_y, shift)
    page_corners_frame = project_plane(page_corners_canvas, (cw, ch), frame_wh, fill, roll, tilt_x, tilt_y, shift)
    homography = cv2.getPerspectiveTransform(canvas_corners, frame_canvas_corners)

    desk = desk_texture(rng, frame_wh, desk_base)
    if no_page:
        frame = desk
    else:
        warped = cv2.warpPerspective(canvas, homography, frame_wh, flags=cv2.INTER_LINEAR).astype(np.float32)
        mask = cv2.warpPerspective(np.full((ch, cw), 255, np.uint8), homography, frame_wh, flags=cv2.INTER_LINEAR)
        mask = mask.astype(np.float32)[:, :, None] / 255.0
        shadow = cv2.GaussianBlur(np.roll(mask[:, :, 0], (12, 8), axis=(0, 1)), (0, 0), 10)[:, :, None]
        frame = desk * (1 - 0.35 * shadow) * (1 - mask) + warped * mask

    frame = frame * 0.97                      # paper never quite hits white under normal exposure
    glare_center = None
    glare_strength = 0.0
    if glare:
        idx = page_corners_frame.mean(axis=0) + rng.uniform(-0.15, 0.15, 2) * np.ptp(page_corners_frame, axis=0)
        glare_center, glare_strength = (float(idx[0]), float(idx[1])), 230.0
    elif rng.random() < 0.5 and not no_page:
        glare_center = (float(rng.uniform(0, frame_wh[0])), float(rng.uniform(0, frame_wh[1])))
        glare_strength = float(rng.uniform(10, 40))
    gradient_min = float(rng.uniform(0.65, 0.9))
    frame = apply_lighting(frame, rng, glare_center, glare_strength, gradient_min)
    if dark:
        frame = frame * 0.18

    frame = np.clip(frame + rng.normal(0, 2.5, frame.shape), 0, 255).astype(np.uint8)
    if hand and not no_page:
        frame = draw_hand(frame, rng, page_corners_frame)
    sigma = float(rng.uniform(4.0, 6.0)) if blur else float(rng.uniform(0.3, 0.9))
    frame = cv2.GaussianBlur(frame, (0, 0), sigma)
    quality = int(jpeg_quality or rng.integers(70, 92))
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    frame = cv2.imdecode(buf, cv2.IMREAD_COLOR) if ok else frame

    params = dict(seed=seed, roll=roll, tilt_x=tilt_x, tilt_y=tilt_y, fill=fill, ruled=ruled, n_lines=n_lines,
                  blur=blur, glare=glare, dark=dark, hand=hand, no_page=no_page, partial=partial, aruco=aruco,
                  weak_edges=weak_edges, jpeg_quality=quality, sigma=sigma, page_wh=(page_px_w, page_h))
    return SynthSample(frame, page_corners_frame, page, params)


def corner_error_fraction(pred: np.ndarray, truth: np.ndarray) -> float:
    """Mean corner distance (after best cyclic alignment) as a fraction of the page diagonal."""
    pred = np.asarray(pred, np.float32).reshape(4, 2)
    truth = np.asarray(truth, np.float32).reshape(4, 2)
    diag = float(np.linalg.norm(truth[0] - truth[2]))
    best = float("inf")
    for shift in range(4):
        rolled = np.roll(pred, shift, axis=0)
        best = min(best, float(np.linalg.norm(rolled - truth, axis=1).mean()))
    return best / max(diag, 1e-6)


def save(sample: SynthSample, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), sample.image)
    return path


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--out", default="runtime/debug/synth")
    ap.add_argument("--flag", action="append", default=[], help="blur|glare|dark|hand|no_page|partial|aruco|weak_edges")
    args = ap.parse_args()
    for i in range(args.n):
        s = render(i, **{f: True for f in args.flag})
        vis = s.image.copy()
        cv2.polylines(vis, [s.corners.astype(np.int32)], True, (0, 255, 0), 3)
        p = save(SynthSample(vis, s.corners, s.page), Path(args.out) / f"synth_{i:03d}.jpg")
        print(p, {k: (round(v, 2) if isinstance(v, float) else v) for k, v in s.params.items() if k in ("roll", "tilt_x", "tilt_y", "fill")})
