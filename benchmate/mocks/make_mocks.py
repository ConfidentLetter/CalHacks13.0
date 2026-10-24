"""Generates the mock twins every terminal codes against on day one.

Run: python mocks/make_mocks.py
Writes twin_ok.json, twin_sda_swapped.json, twin_5v.json next to this file.
The tiny build_nets() here is a reference for T1, not the real implementation.
"""
import copy
import json
import re
from pathlib import Path

HERE = Path(__file__).parent
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]


def node_of(hole):
    """Breadboard connectivity: a-e of a row share a node, f-j share another, rails are one node each."""
    if hole is None:
        return None
    if hole.startswith("RAIL_"):
        return hole
    m = re.fullmatch(r"([A-J])(\d+)", hole)
    col, row = m.group(1), int(m.group(2))
    return f"R{row}{'L' if col in 'ABCDE' else 'R'}"


def build_nets(components, wires):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        parent[find(a)] = find(b)

    holes_by_node = {}
    for w in wires:
        a, b = node_of(w["end_a"]["hole"]), node_of(w["end_b"]["hole"])
        for end, node in ((w["end_a"], a), (w["end_b"], b)):
            if node:
                holes_by_node.setdefault(node, set()).add(end["hole"])
        if a and b:
            union(a, b)
    members_by_node = {}
    for c in components:
        for p in c["pins"]:
            node = node_of(p["hole"])
            if node:
                find(node)
                holes_by_node.setdefault(node, set()).add(p["hole"])
                members_by_node.setdefault(node, []).append(f"{c['id']}.{p['name']}")
    groups = {}
    for node in list(parent):
        root = find(node)
        g = groups.setdefault(root, {"holes": set(), "members": []})
        g["holes"] |= holes_by_node.get(node, set())
        g["members"] += members_by_node.get(node, [])
    nets = [g for g in groups.values() if g["members"]]
    return [
        {"id": f"net_{i+1}", "holes": sorted(g["holes"]), "members": sorted(g["members"])}
        for i, g in enumerate(sorted(nets, key=lambda g: sorted(g["members"])))
    ]


def wire(wid, color, a, b, conf=0.9):
    return {"id": wid, "color": color, "end_a": {"hole": a, "pixel": [0, 0]},
            "end_b": {"hole": b, "pixel": [0, 0]}, "confidence": conf}


components = [
    {"id": "esp32_1", "part_id": "esp32-devkitc", "label_text": "ESP32-WROOM-32",
     "bbox": [120, 80, 260, 520], "confidence": 0.95,
     "pins": [{"name": "3V3", "hole": "C1"}, {"name": "GND", "hole": "C14"},
              {"name": "5V", "hole": "C19"}, {"name": "GPIO21", "hole": "J15"},
              {"name": "GPIO22", "hole": "J18"}]},
    {"id": "bme280_1", "part_id": "bme280", "label_text": "GY-BME280",
     "bbox": [620, 300, 90, 70], "confidence": 0.88,
     "pins": [{"name": "VIN", "hole": "B40"}, {"name": "GND", "hole": "B41"},
              {"name": "SCL", "hole": "B42"}, {"name": "SDA", "hole": "B43"}]},
]

ok_wires = [
    wire("w_red_1", "red", "A1", "RAIL_TOP_PLUS"),
    wire("w_red_2", "red", "A40", "RAIL_TOP_PLUS"),
    wire("w_black_1", "black", "A14", "RAIL_TOP_MINUS"),
    wire("w_black_2", "black", "A41", "RAIL_TOP_MINUS"),
    wire("w_yellow_1", "yellow", "A43", "I15", 0.86),  # sensor SDA -> GPIO21
    wire("w_green_1", "green", "A42", "I18", 0.84),    # sensor SCL -> GPIO22
]


def twin(frame_id, wires):
    return {"frame_id": frame_id, "timestamp": "2026-10-24T10:00:00-07:00",
            "board": {"type": "breadboard_830", "homography": IDENTITY},
            "components": copy.deepcopy(components), "wires": wires,
            "nets": build_nets(components, wires)}


swapped = copy.deepcopy(ok_wires)
swapped[4]["end_b"]["hole"] = "I18"   # SDA now on GPIO22
swapped[5]["end_b"]["hole"] = "I15"   # SCL now on GPIO21

five_v = copy.deepcopy(ok_wires)
five_v[1] = wire("w_red_2", "red", "A40", "RAIL_BOTTOM_PLUS")
five_v.append(wire("w_red_3", "red", "A19", "RAIL_BOTTOM_PLUS"))  # 5V pin feeds bottom rail

for name, w in [("twin_ok", ok_wires), ("twin_sda_swapped", swapped), ("twin_5v", five_v)]:
    (HERE / f"{name}.json").write_text(json.dumps(twin(name, w), indent=2))
    print("wrote", name)
