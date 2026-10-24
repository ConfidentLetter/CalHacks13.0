"""Tunables for wire detection. Edit these (not the code) when tuning on real photos."""
from __future__ import annotations

# HSV ranges (OpenCV scale: H 0-179, S 0-255, V 0-255). Red wraps around 0/180 -> two ranges.
# Tune against real photos; keep white/black out (invisible on the board / look like holes).
WIRE_COLORS: dict[str, list[tuple[tuple[int, int, int], tuple[int, int, int]]]] = {
    "red": [((0, 110, 70), (7, 255, 255)), ((168, 110, 70), (179, 255, 255))],
    "orange": [((8, 120, 110), (19, 255, 255))],
    "yellow": [((20, 100, 110), (36, 255, 255))],
    "green": [((37, 70, 50), (88, 255, 255))],
    "blue": [((92, 80, 50), (132, 255, 255))],
}

WIRE_PARAMS = {
    "clahe_clip": 2.0,
    "glare_v": 245,                 # pixels brighter than this with low saturation are glare, not wire
    "glare_s": 50,
    "open_pitches": 0.28,           # removes the board's printed rail lines (thin) and speckle
    "close_pitches": 0.30,          # spec: ~0.3 pitch
    "min_len_pitches": 1.5,         # drop blobs shorter than this (bbox diagonal)
    "spur_pitches": 0.7,            # skeleton branches shorter than this are spurs, not wire ends
    "extend_pitches": 0.47,         # insulation tip -> hole centre (bare pin length); measured 0.47 on synth — TUNE on real photos
    "exclude_margin_pitches": 0.1,
    "crossing_conf": 0.5,
    "hidden_end_conf": 0.3,         # one end disappears under a component box
    "pcb_inside_fraction": 0.5,     # a colour blob mostly inside a component box is the PCB, not a wire ...
    "pcb_min_halfwidth_mm": 1.6,    # ... provided it is fat; a thin blob inside the box is a wire over the PCB
    "tip_walk_pitches": 1.5,        # how far past the skeleton end to look for the insulation tip
    "fragment_min_pitches": 0.5,    # shorter blobs are noise; longer ones may still be fragments to merge
    "extrapolate_max_pitches": 3.0, # how far an occluded end may be pushed through a crossing wire
    "crossing_span_pitches": 1.0,   # occluded span shorter than this = a crossing wire (push through it)
    "extrapolated_conf": 0.6,       # confidence ceiling for an end found by extrapolation
    "dir_trace_pitches": 1.2,       # skeleton length used to estimate the direction at an end
    "straight_through_cos": 0.5,    # at a junction, branch directions must be this anti-parallel to pair up
    "junction_merge_pitches": 1.5,  # junctions closer than this are one crossing
    "merge_max_gap_pitches": 12.0,  # fragments farther apart than this are not the same wire
}
