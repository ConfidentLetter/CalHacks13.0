"""Jumper-wire detection: colour segmentation in the warped board image -> skeleton endpoints -> holes.

detect_wires(frame_path, homography, exclude_boxes) returns wires per contracts/twin.schema.json with
`pixel` in ORIGINAL image coordinates. Set env BM_DEBUG_WIRES=1 (or call detect_wires_debug) to write
runtime/debug/wires_<frame>.png with masks, skeletons and snapped holes drawn on top.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

import cv2
import numpy as np

from . import board
from .holes import hole_blob_mask
from .skeleton import (_branch_dir_at, _pair_branches_at_junctions, _prune_spurs,
                       _skeleton_graph)
from .paths import debug_dir
from .telemetry import log
from .warp import as_matrix, read_frame, to_original, warp_image

from .params import WIRE_COLORS, WIRE_PARAMS  # noqa: F401  (tunables live in params.py)


# ----------------------------------------------------------------------------- masks

def _board_roi_mask(shape) -> np.ndarray:
    """Only look at the board rectangle (plus a pitch) — never at the markers or the mat."""
    cfg = board.BOARD_CONFIG
    s = cfg["px_per_mm"]
    bx, by = cfg["board_tl_mm"]
    bw, bh = cfg["board_size_mm"]
    m = np.zeros(shape[:2], np.uint8)
    pad = cfg["pitch_mm"]
    cv2.rectangle(m, (int((bx - pad) * s), int((by - pad) * s)), (int((bx + bw + pad) * s), int((by + bh + pad) * s)), 255, -1)
    return m


def _exclude_mask(shape, exclude_boxes, H) -> np.ndarray:
    m = np.zeros(shape[:2], np.uint8)
    if not exclude_boxes:
        return m
    margin = WIRE_PARAMS["exclude_margin_pitches"] * board.pitch_px()
    for x, y, w, h in exclude_boxes:
        corners = np.array([[x, y], [x + w, y], [x + w, y + h], [x, y + h]], np.float64)
        wc = cv2.perspectiveTransform(corners.reshape(-1, 1, 2), as_matrix(H)).reshape(-1, 2)
        poly = (wc + (wc - wc.mean(axis=0)) / (np.linalg.norm(wc - wc.mean(axis=0), axis=1, keepdims=True) + 1e-9) * margin)
        cv2.fillConvexPoly(m, np.round(poly).astype(np.int32), 255)
    return m


def _colour_masks(warped: np.ndarray, ignore: np.ndarray) -> dict[str, np.ndarray]:
    hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
    clahe = cv2.createCLAHE(clipLimit=WIRE_PARAMS["clahe_clip"], tileGridSize=(8, 8))
    hsv[..., 2] = clahe.apply(hsv[..., 2])
    glare = ((hsv[..., 2] >= WIRE_PARAMS["glare_v"]) & (hsv[..., 1] <= WIRE_PARAMS["glare_s"])).astype(np.uint8) * 255
    keep = cv2.bitwise_and(cv2.bitwise_not(ignore), cv2.bitwise_not(glare))
    p = board.pitch_px()
    k_open = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(WIRE_PARAMS["open_pitches"] * p) | 1,) * 2)
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (int(WIRE_PARAMS["close_pitches"] * p) | 1,) * 2)
    out = {}
    for color, ranges in WIRE_COLORS.items():
        m = np.zeros(hsv.shape[:2], np.uint8)
        for lo, hi in ranges:
            m |= cv2.inRange(hsv, np.array(lo, np.uint8), np.array(hi, np.uint8))
        m = cv2.bitwise_and(m, keep)
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, k_close)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k_open)
        out[color] = m
    return out


# ----------------------------------------------------------------------------- endpoints


def _blob_wires(blob: np.ndarray, pitch: float) -> tuple[list[tuple[list[dict], bool]], np.ndarray]:
    """One blob -> list of (two end records, crossing_flag); plus the skeleton for debugging.
    Touching / crossing wires of the same colour are separated at skeleton junctions."""
    from skimage.morphology import skeletonize
    sk = skeletonize(blob > 0).astype(np.uint8)
    sk = _prune_spurs(sk, int(WIRE_PARAMS["spur_pitches"] * pitch))
    nodes, branches = _skeleton_graph(sk, pitch)
    if not branches:
        return [], sk
    pairs = _pair_branches_at_junctions(nodes, branches, pitch)
    used: set[int] = set()
    wires = []
    L = max(3, int(WIRE_PARAMS["dir_trace_pitches"] * pitch))

    def _end_record(bi: int, which: int) -> dict:
        br = branches[bi]
        node = nodes[br["nodes"][which]]
        d = _branch_dir_at(br, which, L)
        term = np.array(br["pixels"][0 if which == 0 else -1], np.float64)
        if node["kind"] == "end":
            d = _pca_direction(blob, term, WIRE_PARAMS["dir_trace_pitches"] * pitch, d)
            tip = _walk_to_tip(blob, term, d, int(WIRE_PARAMS["tip_walk_pitches"] * pitch))
            at_junction = False
        else:                                                   # wire terminates ON another wire (T)
            tip = np.array(node["pos"], np.float64) + d * 0.5 * pitch
            at_junction = True
        pt = tip + d * WIRE_PARAMS["extend_pitches"] * pitch
        return {"raw": np.array([term[1], term[0]]), "tip": np.array([tip[1], tip[0]]),
                "pt": np.array([pt[1], pt[0]]), "dir": np.array([d[1], d[0]]), "at_junction": at_junction}

    # start a traversal from every branch end that is terminal (endpoint node or unpaired at a junction)
    starts = [(bi, w) for bi, br in enumerate(branches) for w in (0, 1) if (bi, w) not in pairs]
    for bi, w in starts:
        if bi in used:
            continue
        first = _end_record(bi, w)
        crossing = False
        cur_b, cur_w = bi, w
        while True:
            used.add(cur_b)
            other = 1 - cur_w
            if (cur_b, other) not in pairs:
                last = _end_record(cur_b, other)
                break
            crossing = True
            nb_b, nb_w = pairs[(cur_b, other)]
            if nb_b in used:                                    # loop; stop here
                last = _end_record(cur_b, other)
                break
            cur_b, cur_w = nb_b, nb_w
        crossing = crossing or first["at_junction"] or last["at_junction"]
        wires.append(([first, last], crossing))
    return wires, sk


def _pca_direction(blob: np.ndarray, end_rc: np.ndarray, radius: float, fallback: np.ndarray) -> np.ndarray:
    """Outward direction (row, col) at an end from the principal axis of the blob pixels around it.
    A wire cut by a crossing wire leaves a hooked skeleton; the blob's own shape is more reliable."""
    r0, c0 = int(end_rc[0]), int(end_rc[1])
    rad = int(radius)
    sub = blob[max(r0 - rad, 0):r0 + rad + 1, max(c0 - rad, 0):c0 + rad + 1]
    rs, cs = np.where(sub > 0)
    if rs.size < 20:
        return fallback
    pts = np.column_stack([rs + max(r0 - rad, 0), cs + max(c0 - rad, 0)]).astype(np.float64)
    keep = np.linalg.norm(pts - end_rc, axis=1) <= radius
    pts = pts[keep]
    if pts.shape[0] < 20:
        return fallback
    centred = pts - pts.mean(axis=0)
    _, vecs = np.linalg.eigh(centred.T @ centred)
    axis = vecs[:, -1]
    outward = end_rc - pts.mean(axis=0)
    if float(axis @ outward) < 0:
        axis = -axis
    if np.any(fallback) and float(axis @ fallback) < 0.3 and np.linalg.norm(outward) < 0.3 * radius:
        return fallback                                     # ambiguous (end near the patch centre): trust skeleton
    return axis


def _walk_to_tip(blob: np.ndarray, start_rc: np.ndarray, d_rc: np.ndarray, max_steps: int) -> np.ndarray:
    """Step along d (row, col) from the skeleton end while still on the blob; returns the last on-blob point.
    The skeleton stops ~half a wire width short of the insulation tip; this recovers that."""
    if not np.any(d_rc):
        return start_rc
    last, misses = start_rc, 0
    for t in range(1, max_steps + 1):
        q = start_rc + d_rc * t
        r, c = int(round(q[0])), int(round(q[1]))
        if not (0 <= r < blob.shape[0] and 0 <= c < blob.shape[1]):
            break
        if blob[max(r - 1, 0):r + 2, max(c - 1, 0):c + 2].any():
            last, misses = q, 0
        else:
            misses += 1
            if misses > 2:
                break
    return last


# ----------------------------------------------------------------------------- snapping

def _near_mask(mask: np.ndarray, pt: np.ndarray) -> bool:
    x, y = int(round(pt[0])), int(round(pt[1]))
    return 0 <= y < mask.shape[0] and 0 <= x < mask.shape[1] and bool(mask[y, x])


def _snap_warped(wx: float, wy: float) -> tuple[str | None, float]:
    """Warped px -> (hole or rail or None, snap distance in px)."""
    cfg = board.BOARD_CONFIG
    s = cfg["px_per_mm"]
    hole, dist_mm = board.nearest_hole_mm(wx / s, wy / s)
    if dist_mm <= cfg["snap_tolerance_pitches"] * cfg["pitch_mm"]:
        return hole, dist_mm * s
    rail = board.rail_at_mm(wx / s, wy / s)
    if rail:
        row = cfg["rail_rows"].get(rail)
        if row is None:
            return rail, 0.0
        ry = (cfg["origin_mm"][1] + row * cfg["pitch_mm"]) * s
        return rail, min(abs(wy - ry), 0.45 * board.pitch_px())
    return None, dist_mm * s


def _snap_end(e: dict, pitch: float) -> None:
    if e["hidden"]:
        e["hole"], e["dist"], e["conf"] = None, 0.0, WIRE_PARAMS["hidden_end_conf"]
        return
    hole, d = _snap_warped(float(e["pt"][0]), float(e["pt"][1]))
    e["hole"], e["dist"] = hole, d
    e["conf"] = max(0.0, 1.0 - d / (0.5 * pitch)) if hole is not None else WIRE_PARAMS["hidden_end_conf"]


def _extrapolate_through(e: dict, occ: np.ndarray, pitch: float) -> None:
    """An occluded end with no partner fragment: the wire most likely continues straight under the
    crossing wire and ends just past it. Walk through the occluder, then snap with reduced confidence."""
    if not np.any(e["dir"]):
        return
    q = e["tip"].copy()
    lead = 0
    while lead < int(0.5 * pitch) and not _near_mask(occ, q):
        q = q + e["dir"]
        lead += 1
    if not _near_mask(occ, q):
        return
    steps = 0
    max_steps = int(WIRE_PARAMS["extrapolate_max_pitches"] * pitch)
    while steps < max_steps and _near_mask(occ, q):
        q = q + e["dir"]
        steps += 1
    if steps == 0 or steps >= max_steps:
        return
    if steps <= WIRE_PARAMS["crossing_span_pitches"] * pitch:
        e["tip"] = q                                  # a wire crossing ours: the end is just past it
        e["pt"] = q + e["dir"] * WIRE_PARAMS["extend_pitches"] * pitch
    # else: the occluder runs along our wire; the end is most likely right where it disappears (keep pt)
    hole, d = _snap_warped(float(e["pt"][0]), float(e["pt"][1]))
    if hole is None:
        return
    e["hole"], e["dist"] = hole, d
    e["conf"] = WIRE_PARAMS["extrapolated_conf"] * max(0.0, 1.0 - d / (0.5 * pitch))
    e["extrapolated"] = True


def _segment_inside(mask: np.ndarray, a: np.ndarray, b: np.ndarray, n: int = 16) -> float:
    """Fraction of sample points on segment a-b that lie inside mask."""
    inside = 0
    for t in np.linspace(0.1, 0.9, n):
        if _near_mask(mask, a + (b - a) * t):
            inside += 1
    return inside / n


def _merge_fragments(cands: list[dict], color: str, occ: np.ndarray, pitch: float) -> list[dict]:
    """Join same-colour fragments whose occluded ends face each other across an occluder
    (a crossing wire of another colour, or a component box)."""
    max_gap = WIRE_PARAMS["merge_max_gap_pitches"] * pitch
    mine = [c for c in cands if c["color"] == color]
    others = [c for c in cands if c["color"] != color]
    changed = True
    while changed and len(mine) > 1:
        changed = False
        pairs = []
        for i, a in enumerate(mine):
            for j, b in enumerate(mine):
                if j <= i:
                    continue
                for ia, ea in enumerate(a["ends"]):
                    if not ea["occluded"]:
                        continue
                    for ib, eb in enumerate(b["ends"]):
                        if not eb["occluded"]:
                            continue
                        gap = eb["tip"] - ea["tip"]
                        dist = float(np.linalg.norm(gap))
                        if dist > max_gap or dist < 1e-6:
                            continue
                        u = gap / dist
                        if dist > 2 * pitch and (float(ea["dir"] @ u) < 0.5 or float(eb["dir"] @ -u) < 0.5):
                            continue
                        if _segment_inside(occ, ea["tip"], eb["tip"]) < 0.4:
                            continue
                        pairs.append((dist, i, j, ia, ib))
        if not pairs:
            break
        pairs.sort(key=lambda t: t[0])
        _, i, j, ia, ib = pairs[0]
        a, b = mine[i], mine[j]
        merged = {"color": color, "ends": [a["ends"][1 - ia], b["ends"][1 - ib]],
                  "crossing": a["crossing"] or b["crossing"], "parts": a["parts"] + b["parts"]}
        mine = [c for k, c in enumerate(mine) if k not in (i, j)] + [merged]
        changed = True
    return others + mine


# ----------------------------------------------------------------------------- main

def detect_wires(frame_path: str, homography, exclude_boxes: list[list[float]] | None = None) -> list[dict]:
    """Wires per twin.schema.json. exclude_boxes = component bboxes [x,y,w,h] to mask out (PCBs are colored too)."""
    debug = os.environ.get("BM_DEBUG_WIRES", "") not in ("", "0")
    wires, _ = _detect(frame_path, homography, exclude_boxes, debug=debug)
    return wires


def detect_wires_debug(frame_path: str, homography, exclude_boxes=None, out_path: str | None = None) -> tuple[list[dict], str]:
    """Same as detect_wires but always writes the debug image; returns (wires, debug_image_path)."""
    return _detect(frame_path, homography, exclude_boxes, debug=True, out_path=out_path)


def _detect(frame_path, homography, exclude_boxes, debug: bool, out_path: str | None = None, return_candidates: bool = False):
    t0 = time.perf_counter()
    img = read_frame(frame_path)
    H = as_matrix(homography)
    pitch = board.pitch_px()
    warped = warp_image(img, H)

    ignore = cv2.bitwise_not(_board_roi_mask(warped.shape))
    ignore |= hole_blob_mask(warped)
    excl_full = _exclude_mask(warped.shape, exclude_boxes, H)
    masks = _colour_masks(warped, ignore)
    k = int(0.3 * pitch) * 2 + 1
    k_near = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))

    # pass 1: connected components per colour. A blob mostly inside a component box IS the component
    # (PCB); only the part of it inside the box is dropped — a same-colour wire running over the PCB
    # keeps its outside pieces, which the merge step joins across the PCB.
    min_len = WIRE_PARAMS["min_len_pitches"] * pitch
    frag_len = WIRE_PARAMS["fragment_min_pitches"] * pitch
    pcb_mask = np.zeros(excl_full.shape, np.uint8)
    all_colours = np.zeros(excl_full.shape, np.uint8)
    blobs: list[tuple[str, np.ndarray, tuple[int, int]]] = []       # (colour, crop mask, (x0, y0))

    def _add_blob(color, crop, x0, y0):
        ys, xs = np.where(crop > 0)
        if xs.size == 0:
            return
        w, h = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        all_colours[y0:y0 + crop.shape[0], x0:x0 + crop.shape[1]][crop > 0] = 255
        if (w * w + h * h) ** 0.5 >= frag_len:
            blobs.append((color, crop, (x0, y0)))

    # per-box masks so a thin sliver of a PCB (its edge ring) is dropped once a fat blob of the
    # same colour identified that box's PCB colour
    box_masks = [_exclude_mask(excl_full.shape, [b], H) for b in (exclude_boxes or [])]
    ccs = []
    for color, m in masks.items():
        n, labels, stats, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            sel = (labels[y:y + h, x:x + w] == i).astype(np.uint8)
            frac = [float((bm[y:y + h, x:x + w] > 0)[sel > 0].mean()) for bm in box_masks]
            fat = bool(cv2.distanceTransform(sel, cv2.DIST_L2, 3).max()
                       >= WIRE_PARAMS["pcb_min_halfwidth_mm"] * board.BOARD_CONFIG["px_per_mm"])
            ccs.append((color, sel, (x, y, w, h), frac, fat))
    pcb_colours = {(b, color) for color, _, _, frac, fat in ccs
                   for b, f in enumerate(frac) if fat and f >= WIRE_PARAMS["pcb_inside_fraction"]}
    for color, sel, (x, y, w, h), frac, fat in ccs:
        pcb_boxes = [b for b, f in enumerate(frac)
                     if f >= WIRE_PARAMS["pcb_inside_fraction"] and (fat or (b, color) in pcb_colours)]
        if pcb_boxes:
            box = np.zeros(sel.shape, bool)
            for b in pcb_boxes:
                box |= box_masks[b][y:y + h, x:x + w] > 0
            pcb_mask[y:y + h, x:x + w][(sel > 0) & box] = 255
            outside = (sel > 0) & ~box
            if not outside.any():
                continue
            n2, lab2 = cv2.connectedComponents(outside.astype(np.uint8), connectivity=8)
            for j in range(1, n2):
                _add_blob(color, (lab2 == j).astype(np.uint8), x, y)
            continue
        _add_blob(color, sel, x, y)
    k_small = int(0.15 * pitch) * 2 + 1
    pcb_touch = cv2.dilate(pcb_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_small, k_small)))

    # pass 2: skeleton endpoints; occluders for a colour = PCBs + every OTHER colour's wires
    candidates = []
    for color, m in masks.items():
        occ = cv2.dilate(pcb_mask | (all_colours & ~m), k_near)
        for bcolor, crop, (bx, by) in blobs:
            if bcolor != color:
                continue
            pad = 2
            blob = cv2.copyMakeBorder(crop, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
            x0, y0 = bx - pad, by - pad
            found, sk = _blob_wires(blob, pitch)
            for ends, crossing in found:
                for e in ends:
                    e["raw"] = e["raw"] + np.array([x0, y0])
                    e["tip"] = e["tip"] + np.array([x0, y0])
                    e["pt"] = e["pt"] + np.array([x0, y0])
                    e["occluded"] = _near_mask(occ, e["pt"]) or _near_mask(occ, e["tip"])
                    # hidden = the wire runs INTO a PCB: its tip touches the PCB and the extended point is inside it
                    e["hidden"] = _near_mask(pcb_touch, e["tip"]) and _near_mask(pcb_mask, e["pt"])
                    _snap_end(e, pitch)
                    if e["at_junction"]:
                        e["conf"] = min(e["conf"], WIRE_PARAMS["crossing_conf"])
                candidates.append({"color": color, "ends": ends, "crossing": crossing, "parts": [(sk, (x0, y0))]})
        candidates = _merge_fragments(candidates, color, occ, pitch)
        for c in candidates:
            if c["color"] != color:
                continue
            for e in c["ends"]:
                if e["occluded"] and not e["hidden"] and e["hole"] is None:
                    _extrapolate_through(e, occ, pitch)

    def _long_enough(c):
        span = float(np.linalg.norm(c["ends"][0]["tip"] - c["ends"][1]["tip"]))
        return span >= min_len or len(c["parts"]) >= 2

    candidates = [c for c in candidates if _long_enough(c)]
    wires = []
    for color in WIRE_COLORS:
        same = [c for c in candidates if c["color"] == color and not all(e["hole"] is None for e in c["ends"])]
        same.sort(key=lambda c: min(e["pt"][0] for e in c["ends"]))
        for n, c in enumerate(same, 1):
            ends = sorted(c["ends"], key=lambda e: e["pt"][0])          # end_a is the left endpoint
            orig = to_original(np.array([e["pt"] for e in ends]), H)
            conf = min(e["conf"] for e in ends)
            if c["crossing"]:
                conf = min(conf, WIRE_PARAMS["crossing_conf"])
            c["conf"] = round(float(conf), 3)
            c["id"] = f"w_{color}_{n}"
            wires.append({
                "id": c["id"],
                "color": color,
                "end_a": {"hole": ends[0]["hole"], "pixel": [round(float(orig[0][0]), 1), round(float(orig[0][1]), 1)]},
                "end_b": {"hole": ends[1]["hole"], "pixel": [round(float(orig[1][0]), 1), round(float(orig[1][1]), 1)]},
                "confidence": c["conf"],
            })

    dbg_path = ""
    if debug:
        dbg_path = _write_debug(frame_path, warped, masks, ignore, pcb_mask, candidates, out_path)
    log("detect_wires", (time.perf_counter() - t0) * 1000, n_wires=len(wires),
        n_low_conf=sum(w["confidence"] < 0.6 for w in wires), debug=dbg_path or None)
    if return_candidates:
        return wires, dbg_path, candidates
    return wires, dbg_path


# ----------------------------------------------------------------------------- debug image

_TINT = {"red": (0, 0, 255), "orange": (0, 140, 255), "yellow": (0, 230, 230), "green": (0, 200, 0), "blue": (255, 120, 0)}


def _write_debug(frame_path, warped, masks, ignore, excl, candidates, out_path) -> str:
    vis = cv2.addWeighted(warped, 0.55, np.full_like(warped, 255), 0.45, 0)
    vis[ignore > 0] = (vis[ignore > 0] * 0.6).astype(np.uint8)
    vis[excl > 0] = (0.5 * vis[excl > 0] + 0.5 * np.array([180, 0, 180])).astype(np.uint8)
    for color, m in masks.items():
        vis[m > 0] = (0.4 * vis[m > 0] + 0.6 * np.array(_TINT[color])).astype(np.uint8)
    # model holes faintly
    for h in board.iter_holes():
        x, y = board.hole_px(h)
        cv2.circle(vis, (int(x), int(y)), 2, (120, 120, 120), -1)
    pitch = board.pitch_px()
    for c in candidates:
        for sk, (x0, y0) in c["parts"]:
            ys, xs = np.where(sk > 0)
            vis[ys + y0, xs + x0] = (255, 255, 255)
        for e in c["ends"]:
            ex, ey = int(round(e["pt"][0])), int(round(e["pt"][1]))
            hole = e["hole"]
            ok = hole is not None and (hole.startswith("RAIL") or e["dist"] <= 0.35 * pitch)
            cv2.circle(vis, (ex, ey), int(0.35 * pitch), (0, 200, 0) if ok else (0, 0, 255), 2)
            if hole:
                hx, hy = board.hole_px(hole)
                cv2.line(vis, (ex, ey), (int(hx), int(hy)), (0, 0, 0), 1)
                cv2.putText(vis, hole, (ex + 8, ey - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 2, cv2.LINE_AA)
                cv2.putText(vis, hole, (ex + 8, ey - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1, cv2.LINE_AA)
            elif e["hidden"]:
                cv2.putText(vis, "hidden", (ex + 8, ey - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (180, 0, 180), 1, cv2.LINE_AA)
        if "id" not in c:
            continue
        mid = (c["ends"][0]["pt"] + c["ends"][1]["pt"]) / 2
        tag = f"{c['id']} {c['conf']:.2f}" + (" X" if c["crossing"] else "")
        cv2.putText(vis, tag, (int(mid[0]), int(mid[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 3, cv2.LINE_AA)
        cv2.putText(vis, tag, (int(mid[0]), int(mid[1])), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
    out = Path(out_path) if out_path else debug_dir() / f"wires_{Path(frame_path).stem}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), vis)
    return str(out)
