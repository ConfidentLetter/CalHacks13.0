"""Skeleton analysis for wire blobs: neighbour counts, spur pruning, and the skeleton graph
(endpoint / junction nodes, branches) with straight-through pairing at junctions."""
from __future__ import annotations

import cv2
import numpy as np

from .params import WIRE_PARAMS

_NBR = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def _neighbour_count(sk: np.ndarray) -> np.ndarray:
    k = np.ones((3, 3), np.float32)
    k[1, 1] = 0
    return cv2.filter2D(sk.astype(np.float32), -1, k, borderType=cv2.BORDER_CONSTANT).astype(np.int32) * sk


def _trace_from(sk: np.ndarray, start: tuple[int, int], max_len: int) -> list[tuple[int, int]]:
    """Walk from an endpoint along the skeleton until a junction / endpoint / max_len."""
    nb = _neighbour_count(sk)
    path = [start]
    prev, cur = None, start
    while len(path) < max_len:
        r, c = cur
        nxt = [(r + dr, c + dc) for dr, dc in _NBR
               if 0 <= r + dr < sk.shape[0] and 0 <= c + dc < sk.shape[1] and sk[r + dr, c + dc] and (r + dr, c + dc) != prev
               and (r + dr, c + dc) not in path[-3:]]
        if len(nxt) != 1 or nb[cur] > 2 and cur != start:
            break
        prev, cur = cur, nxt[0]
        path.append(cur)
    return path


def _prune_spurs(sk: np.ndarray, spur_len: int) -> np.ndarray:
    """Remove short terminal branches that end at a junction (skeleton artefacts of a thick, slanted
    or notched wire end). Iterates until stable."""
    sk = sk.copy()
    for _ in range(4):
        nodes, branches = _skeleton_graph(sk, pitch=None)
        removed = False
        for br in branches:
            kinds = {nodes[n]["kind"] for n in br["nodes"]}
            if kinds == {"end", "junction"} and len(br["pixels"]) <= spur_len:
                for r, c in br["pixels"]:
                    sk[r, c] = 0
                removed = True
        if not removed:
            break
        # re-thin so a former junction pixel with 2 neighbours is a plain path pixel again
        from skimage.morphology import skeletonize
        sk = skeletonize(sk > 0).astype(np.uint8)
    return sk



def _endpoint_direction(sk: np.ndarray, end: tuple[int, int], back: int) -> np.ndarray:
    path = _trace_from(sk, end, back)
    if len(path) < 3:
        return np.zeros(2)
    a, b = np.array(path[-1], np.float64), np.array(path[0], np.float64)
    d = b - a                                   # (row, col) pointing outwards
    n = np.linalg.norm(d)
    return d / n if n > 0 else np.zeros(2)


def _skeleton_graph(sk: np.ndarray, pitch: float):
    """Decompose a skeleton into nodes (endpoints / junction clusters) and branches between them.
    Returns (nodes, branches): nodes[i] = {"kind": "end"|"junction", "pos": (r, c)};
    branches = [{"pixels": [(r, c) ...] ordered, "nodes": (node_a, node_b)}]."""
    nb = _neighbour_count(sk)
    junction_px = ((sk > 0) & (nb >= 3)).astype(np.uint8)
    # cluster junction pixels (a crossing of thick wires yields a small clump of junction pixels)
    k = np.ones((3, 3), np.uint8)
    n_j, j_labels = cv2.connectedComponents(cv2.dilate(junction_px, k) & sk, connectivity=8)
    j_labels = j_labels * (junction_px > 0)                    # keep labels only on true junction pixels
    nodes: list[dict] = []
    node_at: dict[tuple[int, int], int] = {}
    for j in range(1, n_j):
        rs, cs = np.where(j_labels == j)
        if rs.size == 0:
            continue
        idx = len(nodes)
        nodes.append({"kind": "junction", "pos": (float(rs.mean()), float(cs.mean()))})
        for r, c in zip(rs, cs):
            node_at[(int(r), int(c))] = idx
    for r, c in zip(*np.where((sk > 0) & (nb == 1))):
        idx = len(nodes)
        nodes.append({"kind": "end", "pos": (float(r), float(c))})
        node_at[(int(r), int(c))] = idx

    branch_px = ((sk > 0) & (junction_px == 0)).astype(np.uint8)
    n_b, b_labels = cv2.connectedComponents(branch_px, connectivity=8)
    branches = []
    for b in range(1, n_b):
        rs, cs = np.where(b_labels == b)
        pix = set(zip(rs.tolist(), cs.tolist()))
        # terminals: branch pixels with <= 1 neighbour inside the branch
        def _bn(p):
            return sum((p[0] + dr, p[1] + dc) in pix for dr, dc in _NBR)
        terminals = [p for p in pix if _bn(p) <= 1]
        if len(pix) == 1:
            terminals = [next(iter(pix))] * 2
        if len(terminals) < 2:
            continue
        # order pixels by walking from terminals[0]
        order, seen, cur = [], set(), terminals[0]
        while cur is not None:
            order.append(cur)
            seen.add(cur)
            nxt = [(cur[0] + dr, cur[1] + dc) for dr, dc in _NBR if (cur[0] + dr, cur[1] + dc) in pix and (cur[0] + dr, cur[1] + dc) not in seen]
            cur = nxt[0] if nxt else None
        if len(order) < len(pix) * 0.8:
            order = sorted(pix)                                 # degenerate branch shape; keep going
        ends = []
        for term in (order[0], order[-1]):
            attached = None
            if term in node_at:
                attached = node_at[term]
            else:
                for dr, dc in _NBR:
                    q = (term[0] + dr, term[1] + dc)
                    if q in node_at and nodes[node_at[q]]["kind"] == "junction":
                        attached = node_at[q]
                        break
            if attached is None:                                # isolated terminal: make it an endpoint node
                attached = len(nodes)
                nodes.append({"kind": "end", "pos": (float(term[0]), float(term[1]))})
                node_at[term] = attached
            ends.append(attached)
        branches.append({"pixels": order, "nodes": (ends[0], ends[1])})
    if pitch is not None:
        _merge_close_junctions(nodes, branches, int(WIRE_PARAMS["junction_merge_pitches"] * pitch))
    return nodes, branches


def _merge_close_junctions(nodes: list[dict], branches: list[dict], max_len: int) -> None:
    """Two wires crossing at a shallow angle give two Y-junctions joined by a short stub; treat them
    as one 4-way crossing so straight-through pairing works."""
    while True:
        stub = next((i for i, br in enumerate(branches)
                     if len(br["pixels"]) <= max_len and br["nodes"][0] != br["nodes"][1]
                     and nodes[br["nodes"][0]]["kind"] == "junction" and nodes[br["nodes"][1]]["kind"] == "junction"), None)
        if stub is None:
            return
        a, b = branches[stub]["nodes"]
        pa, pb = nodes[a]["pos"], nodes[b]["pos"]
        nodes[a]["pos"] = ((pa[0] + pb[0]) / 2, (pa[1] + pb[1]) / 2)
        del branches[stub]
        for br in branches:
            br["nodes"] = tuple(a if n == b else n for n in br["nodes"])


def _branch_dir_at(branch: dict, which: int, length: int) -> np.ndarray:
    """Unit (row, col) direction pointing OUT of the branch at end `which` (0 = first pixel, 1 = last)."""
    pts = np.array(branch["pixels"], np.float64)
    if which == 0:
        a, b = pts[min(length, len(pts) - 1)], pts[0]
    else:
        a, b = pts[max(len(pts) - 1 - length, 0)], pts[-1]
    d = b - a
    n = np.linalg.norm(d)
    return d / n if n > 0 else np.zeros(2)


def _pair_branches_at_junctions(nodes, branches, pitch: float) -> dict[tuple[int, int], tuple[int, int]]:
    """At each junction, pair incident branch ends whose directions are most opposite (a wire runs
    straight through a crossing). Unpaired branch ends terminate there. Returns {(branch, end): (branch, end)}."""
    incident: dict[int, list[tuple[int, int]]] = {}
    for bi, br in enumerate(branches):
        for which in (0, 1):
            node = br["nodes"][which]
            if nodes[node]["kind"] == "junction":
                incident.setdefault(node, []).append((bi, which))
    pairs: dict[tuple[int, int], tuple[int, int]] = {}
    L = max(3, int(WIRE_PARAMS["dir_trace_pitches"] * pitch))
    for node, ends in incident.items():
        dirs = {e: _branch_dir_at(branches[e[0]], e[1], L) for e in ends}
        free = list(ends)
        while len(free) >= 2:
            best, best_dot = None, 1.0
            for i in range(len(free)):
                for j in range(i + 1, len(free)):
                    if free[i][0] == free[j][0]:                    # a loop onto itself
                        continue
                    dot = float(dirs[free[i]] @ dirs[free[j]])
                    if dot < best_dot:
                        best, best_dot = (free[i], free[j]), dot
            if best is None or best_dot > -WIRE_PARAMS["straight_through_cos"]:
                break
            pairs[best[0]] = best[1]
            pairs[best[1]] = best[0]
            free = [e for e in free if e not in best]
    return pairs
