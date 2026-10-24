"""Synthetic breadboard renderer: ground-truth images for the geometry test bench.

render_board() draws a top-down board in the warped frame (holes, rails, labels, 4 ArUco
markers, N coloured wires), then applies a random camera-like perspective (tilt, scale,
in-plane rotation), lighting change and noise. It returns the image, the TRUE homography
original -> warped px, and the wire endpoints as hole ids.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from perception_geometry import board

# Nominal insulation colours (BGR) — deliberately a bit off the HSV range centres.
SYNTH_WIRE_BGR = {
    "red": (40, 40, 210),
    "yellow": (40, 210, 230),
    "green": (60, 170, 40),
    "blue": (200, 90, 30),
    "orange": (20, 120, 240),
}
MAT_BGR = (175, 170, 165)
BOARD_BGR = (236, 238, 236)
HOLE_BGR = (38, 38, 40)
RAIL_COLS = [c for c in range(1, 64) if c >= 3 and c <= 61 and (c - 3) % 6 < 5]  # 10 groups of 5


@dataclass
class SynthWire:
    color: str
    hole_a: str
    hole_b: str
    pixel_a: tuple[float, float]   # true endpoint (hole centre) in ORIGINAL image px
    pixel_b: tuple[float, float]


@dataclass
class SynthResult:
    image: np.ndarray
    H_true: np.ndarray                         # original px -> warped px
    wires: list[SynthWire]
    marker_centres_orig: dict[int, tuple[float, float]]
    ppm: float                                 # original px per board mm
    meta: dict = field(default_factory=dict)
    components: list[dict] = field(default_factory=list)   # {"bbox": [x,y,w,h] original px, "holes": [...]}


def _mm_to_px(x_mm: float, y_mm: float) -> tuple[int, int]:
    s = board.BOARD_CONFIG["px_per_mm"]
    return int(round(x_mm * s)), int(round(y_mm * s))


def _draw_hole(canvas, cx, cy, size_px):
    r = size_px // 2
    cv2.rectangle(canvas, (cx - r, cy - r), (cx + r, cy + r), HOLE_BGR, -1)


def draw_blank_board(rng: np.random.Generator, marker_jitter_mm: float = 0.0, hide_markers: set[int] = frozenset()):
    """Top-down canvas in the warped frame. Returns canvas and the jittered marker centres (warped px)."""
    cfg = board.BOARD_CONFIG
    s = cfg["px_per_mm"]
    W, Hh = board.warped_size_px()
    canvas = np.full((Hh, W, 3), MAT_BGR, np.uint8)

    # board body
    bx, by = cfg["board_tl_mm"]
    bw, bh = cfg["board_size_mm"]
    cv2.rectangle(canvas, _mm_to_px(bx, by), _mm_to_px(bx + bw, by + bh), BOARD_BGR, -1)

    ox, oy = cfg["origin_mm"]
    p = cfg["pitch_mm"]
    hole_px = int(round(1.0 * s))

    # centre channel groove
    e_y = oy + board.row_offset_pitches(cfg["letters_top_to_bottom"][4]) * p
    f_y = oy + board.row_offset_pitches(cfg["letters_top_to_bottom"][5]) * p
    cv2.rectangle(canvas, _mm_to_px(bx + 1.5, (e_y + f_y) / 2 - 1.0), _mm_to_px(bx + bw - 1.5, (e_y + f_y) / 2 + 1.0),
                  (205, 208, 206), -1)

    # terminal holes
    for hole in board.iter_holes():
        cx, cy = _mm_to_px(*board.hole_mm(hole))
        _draw_hole(canvas, cx, cy, hole_px)

    # rail lines + holes
    for rail, row in cfg["rail_rows"].items():
        y = oy + row * p
        line_bgr = (40, 40, 200) if rail.endswith("PLUS") else (200, 80, 40)
        line_off = -1.6 if "TOP" in rail and rail.endswith("PLUS") or "BOTTOM" in rail and rail.endswith("PLUS") else 1.6
        if "BOTTOM" in rail:
            line_off = -line_off
        cv2.line(canvas, _mm_to_px(ox, y + line_off), _mm_to_px(ox + 62 * p, y + line_off), line_bgr, 2)
        for c in RAIL_COLS:
            cx, cy = _mm_to_px(ox + (c - 1) * p, y)
            _draw_hole(canvas, cx, cy, hole_px)

    # printed labels: row letters at both ends, column numbers every 5
    letters = cfg["letters_top_to_bottom"]
    for letter in letters:
        y = oy + board.row_offset_pitches(letter) * p
        for x in (ox - 1.4 * p, ox + 63.0 * p):
            cv2.putText(canvas, letter.lower(), (_mm_to_px(x, y + 0.6)[0], _mm_to_px(x, y + 0.6)[1]),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (90, 90, 90), 1, cv2.LINE_AA)
    for c in range(1, 64):
        if c == 1 or c % 5 == 0:
            for y in (oy - 1.4 * p, oy + (11 + 1.9) * p):
                pt = _mm_to_px(ox + (c - 1) * p - 0.8, y)
                cv2.putText(canvas, str(c), pt, cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1, cv2.LINE_AA)

    # ArUco markers with quiet zone
    adict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    msize = int(round(cfg["marker_size_mm"] * s))
    quiet = int(round(0.25 * msize))
    centres = {}
    for mid, (mx, my) in cfg["markers"].items():
        jx, jy = rng.uniform(-marker_jitter_mm, marker_jitter_mm, 2) if marker_jitter_mm > 0 else (0.0, 0.0)
        cx, cy = (mx + jx) * s, (my + jy) * s
        centres[mid] = (cx, cy)
        if mid in hide_markers:
            continue
        marker = cv2.aruco.generateImageMarker(adict, mid, msize)
        marker = cv2.copyMakeBorder(marker, quiet, quiet, quiet, quiet, cv2.BORDER_CONSTANT, value=255)
        half = marker.shape[0] // 2
        x0, y0 = int(round(cx)) - half, int(round(cy)) - half
        canvas[y0:y0 + marker.shape[0], x0:x0 + marker.shape[1]] = cv2.cvtColor(marker, cv2.COLOR_GRAY2BGR)
    return canvas, centres


def _bezier(a, b, ctrl, n=600):
    t = np.linspace(0, 1, n)[:, None]
    return (1 - t) ** 2 * a + 2 * (1 - t) * t * ctrl + t ** 2 * b


def _random_endpoint(rng, used: set[str], allow_rail=True) -> str:
    cfg = board.BOARD_CONFIG
    while True:
        if allow_rail and rng.random() < 0.2:
            rail = rng.choice(list(cfg["rails"].keys()))
            # a rail "hole" position along x — pick a rail column; return the rail id but place at a rail hole
            return rail
        letter = rng.choice(list(cfg["letters_top_to_bottom"]))
        col = int(rng.integers(1, cfg["n_cols"] + 1))
        hole = f"{letter}{col}"
        if hole not in used:
            return hole


def _endpoint_mm(rng, hole: str, rail_col_used: set[int]) -> tuple[float, float]:
    cfg = board.BOARD_CONFIG
    if hole in cfg["rails"]:
        ox, oy = cfg["origin_mm"]
        p = cfg["pitch_mm"]
        free = [c for c in RAIL_COLS if c not in rail_col_used]
        c = int(rng.choice(free))
        rail_col_used.add(c)
        return ox + (c - 1) * p, oy + cfg["rail_rows"][hole] * p
    return board.hole_mm(hole)


PCB_BGR = [(110, 40, 20), (150, 60, 130), (40, 110, 30)]   # dark blue, purple, green PCBs


def draw_components(canvas, rng, n: int) -> list[dict]:
    """Rectangular PCBs sitting on the board (they are coloured and hide holes). Returns
    {"poly_mm": 4 corners, "holes": covered hole ids}."""
    cfg = board.BOARD_CONFIG
    s = cfg["px_per_mm"]
    p = cfg["pitch_mm"]
    letters = cfg["letters_top_to_bottom"]
    out = []
    taken_cols: set[int] = set()
    for i in range(n):
        for _ in range(50):
            ncols = int(rng.integers(4, 12))
            c0 = int(rng.integers(2, cfg["n_cols"] - ncols))
            if any(c in taken_cols for c in range(c0 - 1, c0 + ncols + 1)):
                continue
            break
        else:
            continue
        half = str(rng.choice(["top", "bottom"]))
        rows = letters[:5] if half == "top" else letters[5:]
        # body covers rows B-E (or F-I) over ncols columns; pins are in the row nearest the channel edge
        r_lo = board.row_offset_pitches(rows[0]) if half == "top" else board.row_offset_pitches(rows[1])
        r_hi = board.row_offset_pitches(rows[3]) if half == "top" else board.row_offset_pitches(rows[4])
        ox, oy = cfg["origin_mm"]
        x0, x1 = ox + (c0 - 0.6) * p, ox + (c0 + ncols - 1 + 0.6) * p
        y0, y1 = oy + (r_lo - 0.45) * p, oy + (r_hi + 0.45) * p
        bgr = PCB_BGR[i % len(PCB_BGR)]
        cv2.rectangle(canvas, _mm_to_px(x0, y0), _mm_to_px(x1, y1), bgr, -1)
        # silkscreen + a chip
        cv2.rectangle(canvas, _mm_to_px(x0 + 1.5, y0 + 1.5), _mm_to_px(x1 - 1.5, y1 - 1.5), (230, 230, 230), 1)
        cv2.rectangle(canvas, _mm_to_px((x0 + x1) / 2 - 2, (y0 + y1) / 2 - 2), _mm_to_px((x0 + x1) / 2 + 2, (y0 + y1) / 2 + 2), (20, 20, 20), -1)
        covered = [f"{r}{c}" for r in rows for c in range(c0, c0 + ncols)
                   if y0 <= board.hole_mm(f"{r}{c}")[1] <= y1]
        taken_cols |= set(range(c0, c0 + ncols))
        out.append({"poly_mm": [(x0, y0), (x1, y0), (x1, y1), (x0, y1)], "holes": covered})
    return out


def draw_wires(canvas, rng, n_wires: int, colors=tuple(SYNTH_WIRE_BGR), used: set[str] | None = None) -> list[tuple[str, str, str, tuple, tuple]]:
    """Draw wires; returns (color, hole_a, hole_b, mm_a, mm_b)."""
    cfg = board.BOARD_CONFIG
    s = cfg["px_per_mm"]
    p = cfg["pitch_mm"]
    used = set(used or ())
    rail_cols: set[int] = set()
    out = []
    for i in range(n_wires):
        color = colors[i % len(colors)] if n_wires <= len(colors) else str(rng.choice(colors))
        for _ in range(100):
            a = _random_endpoint(rng, used)
            b = _random_endpoint(rng, used | {a}, allow_rail=a not in cfg["rails"])
            if a == b:
                continue
            ma = _endpoint_mm(rng, a, set(rail_cols))
            mb = _endpoint_mm(rng, b, set(rail_cols))
            dist = math.dist(ma, mb)
            if 3 * p <= dist <= 45 * p:
                break
        else:
            continue
        used |= {a, b}
        A, B = np.array(ma), np.array(mb)
        d = B - A
        perp = np.array([-d[1], d[0]]) / (np.linalg.norm(d) + 1e-9)
        ctrl = (A + B) / 2 + perp * rng.uniform(-0.18, 0.18) * np.linalg.norm(d)
        pts_mm = _bezier(A, B, ctrl)
        # insulation stops ~0.5 pitch short of each hole; the bare pin continues into the hole
        cut = 0.5 * p + 0.75   # visible insulation ends 0.5 pitch before the hole (round caps add half the width)
        cum = np.r_[0, np.cumsum(np.linalg.norm(np.diff(pts_mm, axis=0), axis=1))]
        keep = (cum >= cut) & (cum <= cum[-1] - cut)
        ins = pts_mm[keep]
        pts_px = (pts_mm * s).astype(np.int32)
        ins_px = (ins * s).astype(np.int32)
        cv2.polylines(canvas, [pts_px], False, (150, 150, 150), int(0.35 * s), cv2.LINE_AA)   # pin metal
        bgr = np.array(SYNTH_WIRE_BGR[color]) + rng.integers(-18, 18, 3)
        bgr = tuple(int(v) for v in np.clip(bgr, 0, 255))
        cv2.polylines(canvas, [ins_px], False, bgr, int(1.5 * s), cv2.LINE_AA)
        hi = tuple(int(min(255, v + 45)) for v in bgr)
        cv2.polylines(canvas, [ins_px], False, hi, max(1, int(0.3 * s)), cv2.LINE_AA)        # highlight
        out.append((color, a, b, ma, mb))
    return out


def random_camera(rng, out_size=(1920, 1080), tilt_deg=8.0, scale_jitter=0.10, roll_deg=6.0,
                  ppm_base=6.8) -> tuple[np.ndarray, float]:
    """Homography warped-px -> original px that looks like a tilted overhead phone camera."""
    cfg = board.BOARD_CONFIG
    s = cfg["px_per_mm"]
    W, Hh = board.warped_size_px()
    cx_w, cy_w = W / 2, Hh / 2
    ppm = ppm_base * (1 + rng.uniform(-scale_jitter, scale_jitter))
    f = 1.4 * out_size[0]
    Z = f / ppm
    ax, ay = np.deg2rad(rng.uniform(-tilt_deg, tilt_deg, 2))
    az = np.deg2rad(rng.uniform(-roll_deg, roll_deg))
    Rx = np.array([[1, 0, 0], [0, math.cos(ax), -math.sin(ax)], [0, math.sin(ax), math.cos(ax)]])
    Ry = np.array([[math.cos(ay), 0, math.sin(ay)], [0, 1, 0], [-math.sin(ay), 0, math.cos(ay)]])
    Rz = np.array([[math.cos(az), -math.sin(az), 0], [math.sin(az), math.cos(az), 0], [0, 0, 1]])
    R = Rx @ Ry @ Rz
    t = np.array([rng.uniform(-8, 8), rng.uniform(-6, 6), Z])
    K = np.array([[f, 0, out_size[0] / 2], [0, f, out_size[1] / 2], [0, 0, 1]])
    # plane point (x_mm, y_mm) -> camera: K [r1 r2 t]
    P = K @ np.column_stack([R[:, 0], R[:, 1], t])
    # warped px -> centred mm
    T = np.array([[1 / s, 0, -cx_w / s], [0, 1 / s, -cy_w / s], [0, 0, 1]])
    M = P @ T
    return M / M[2, 2], ppm


def render_board(seed: int, n_wires: int = 5, out_size=(1920, 1080), marker_jitter_mm: float = 0.0,
                 hide_markers: set[int] = frozenset(), tilt_deg: float = 8.0, scale_jitter: float = 0.10,
                 noise_sigma: float = 4.0, colors=tuple(SYNTH_WIRE_BGR), n_components: int = 0) -> SynthResult:
    rng = np.random.default_rng(seed)
    canvas, marker_centres_w = draw_blank_board(rng, marker_jitter_mm, hide_markers)
    comps = draw_components(canvas, rng, n_components)
    covered = {h for c in comps for h in c["holes"]}
    wires_mm = draw_wires(canvas, rng, n_wires, colors, used=covered)
    M, ppm = random_camera(rng, out_size, tilt_deg, scale_jitter)
    img = cv2.warpPerspective(canvas, M, out_size, flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=MAT_BGR)
    # lighting: gain, offset, slight vignette-ish gradient, blur, noise
    gain = rng.uniform(0.75, 1.15)
    off = rng.uniform(-25, 25)
    yy = np.linspace(-1, 1, out_size[1])[:, None]
    xx = np.linspace(-1, 1, out_size[0])[None, :]
    grad = 1 - 0.12 * (xx ** 2 + yy ** 2)
    img = np.clip(img.astype(np.float32) * gain * grad[..., None] + off, 0, 255)
    img = cv2.GaussianBlur(img, (3, 3), 0)
    if noise_sigma > 0:
        img = img + rng.normal(0, noise_sigma, img.shape).astype(np.float32)
    img = np.clip(img, 0, 255).astype(np.uint8)

    H_true = np.linalg.inv(M)
    H_true /= H_true[2, 2]
    s = board.BOARD_CONFIG["px_per_mm"]

    def w2o(mm):
        pt = np.array([mm[0] * s, mm[1] * s, 1.0])
        q = M @ pt
        return (float(q[0] / q[2]), float(q[1] / q[2]))

    wires = [SynthWire(c, a, b, w2o(ma), w2o(mb)) for c, a, b, ma, mb in wires_mm]
    markers = {k: w2o((v[0] / s, v[1] / s)) for k, v in marker_centres_w.items()}
    components = []
    for c in comps:
        pts = np.array([w2o(q) for q in c["poly_mm"]])
        x0, y0 = pts.min(axis=0)
        x1, y1 = pts.max(axis=0)
        components.append({"bbox": [float(x0), float(y0), float(x1 - x0), float(y1 - y0)], "holes": c["holes"]})
    return SynthResult(img, H_true, wires, markers, ppm, {"seed": seed, "gain": gain}, components)


if __name__ == "__main__":  # quick visual check: python -m perception_geometry.tests.synth
    import sys
    r = render_board(int(sys.argv[1]) if len(sys.argv) > 1 else 0, 6, marker_jitter_mm=1.0, n_components=2)
    out = "runtime/debug/synth_demo.jpg"
    import os
    os.makedirs("runtime/debug", exist_ok=True)
    cv2.imwrite(out, r.image)
    print("wrote", out, [(w.color, w.hole_a, w.hole_b) for w in r.wires])
