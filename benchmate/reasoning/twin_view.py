"""Read-only index over a twin: nets, wires, holes, confidences. Pure functions, no mutation."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from reasoning.config import BOARD_COLUMNS, BOARD_ROWS, RAIL_IDS

_HOLE_RE = re.compile(r"^([A-J])([1-9]\d?)$")


def node_of(hole: str | None) -> str | None:
    """Breadboard connectivity: A-E of a row share a node, F-J share another, each rail is one node."""
    if not hole:
        return None
    if hole.startswith("RAIL_"):
        return hole
    m = _HOLE_RE.match(hole)
    if not m:
        return None
    col, row = m.group(1), int(m.group(2))
    return f"R{row}{'L' if col in 'ABCDE' else 'R'}"


def is_valid_hole(hole: str | None, board_type: str = "breadboard_830") -> bool:
    if not hole:
        return False
    if hole in RAIL_IDS:
        return True
    m = _HOLE_RE.match(hole)
    return bool(m) and int(m.group(2)) <= BOARD_ROWS.get(board_type, 63)


def holes_of_node(node: str) -> list[str]:
    if node.startswith("RAIL_"):
        return [node]
    row, side = node[1:-1], node[-1]
    cols = BOARD_COLUMNS[:5] if side == "L" else BOARD_COLUMNS[5:]
    return [f"{c}{row}" for c in cols]


@dataclass(frozen=True)
class TwinIndex:
    twin: dict[str, Any]
    components: dict[str, dict] = field(init=False)
    wires: dict[str, dict] = field(init=False)
    member_net: dict[str, dict] = field(init=False)
    occupied: frozenset[str] = field(init=False)

    def __post_init__(self) -> None:
        comps = {c["id"]: c for c in self.twin.get("components", [])}
        wires = {w["id"]: w for w in self.twin.get("wires", [])}
        member_net = {m: n for n in self.twin.get("nets", []) for m in n.get("members", [])}
        occ = {p.get("hole") for c in comps.values() for p in c.get("pins", [])}
        occ |= {w["end_a"].get("hole") for w in wires.values()} | {w["end_b"].get("hole") for w in wires.values()}
        object.__setattr__(self, "components", comps)
        object.__setattr__(self, "wires", wires)
        object.__setattr__(self, "member_net", member_net)
        object.__setattr__(self, "occupied", frozenset(h for h in occ if h))

    # ---- lookups -------------------------------------------------------
    @property
    def board_type(self) -> str:
        return self.twin.get("board", {}).get("type", "breadboard_830")

    def net_of(self, component_id: str, pin: str) -> dict | None:
        return self.member_net.get(f"{component_id}.{pin}")

    def pin_hole(self, component_id: str, pin: str) -> str | None:
        comp = self.components.get(component_id)
        if not comp:
            return None
        for p in comp.get("pins", []):
            if p.get("name") == pin:
                return p.get("hole")
        return None

    def pins_of(self, component_id: str, net: dict | None) -> list[str]:
        """Pin names of `component_id` that sit on `net`."""
        if not net:
            return []
        prefix = f"{component_id}."
        return [m[len(prefix):] for m in net.get("members", []) if m.startswith(prefix)]

    def nodes_of_net(self, net: dict) -> set[str]:
        return {n for n in (node_of(h) for h in net.get("holes", [])) if n}

    def wires_on_net(self, net: dict | None) -> list[dict]:
        if not net:
            return []
        nodes = self.nodes_of_net(net)
        return [w for w in self.wires.values()
                if node_of(w["end_a"].get("hole")) in nodes or node_of(w["end_b"].get("hole")) in nodes]

    def wire_at_pin(self, component_id: str, pin: str) -> tuple[dict, str | None] | None:
        """The wire plugged into the pin's row, and the hole at its far end."""
        node = node_of(self.pin_hole(component_id, pin))
        if not node:
            return None
        for w in self.wires.values():
            a, b = w["end_a"].get("hole"), w["end_b"].get("hole")
            if node_of(a) == node:
                return w, b
            if node_of(b) == node:
                return w, a
        return None

    def free_hole_near(self, hole: str | None) -> str | None:
        """An unoccupied hole electrically tied to `hole`, nearest first. Rails return themselves."""
        node = node_of(hole)
        if not node:
            return None
        if node.startswith("RAIL_"):
            return node
        candidates = [h for h in holes_of_node(node) if h not in self.occupied]
        if not candidates:
            return None
        col = hole[0]
        return min(candidates, key=lambda h: abs(ord(h[0]) - ord(col)))

    def best_hole_on_net_of(self, component_id: str, pin: str) -> str | None:
        """Where a new wire should land to reach `component_id.pin`: its rail if it has one, else a free hole beside it."""
        net = self.net_of(component_id, pin)
        if net:
            rails = [h for h in net.get("holes", []) if h.startswith("RAIL_")]
            if rails:
                return rails[0]
        return self.free_hole_near(self.pin_hole(component_id, pin))

    # ---- confidence ----------------------------------------------------
    def confidence_of(self, element_id: str) -> float | None:
        el = self.components.get(element_id) or self.wires.get(element_id)
        return None if el is None else float(el.get("confidence", 1.0))

    def min_confidence(self, element_ids: list[str]) -> float:
        confs = [c for c in (self.confidence_of(e) for e in element_ids) if c is not None]
        return round(min(confs), 3) if confs else 0.5

    def weakest(self, element_ids: list[str]) -> tuple[str, float] | None:
        pairs = [(e, c) for e in element_ids for c in [self.confidence_of(e)] if c is not None]
        return min(pairs, key=lambda p: p[1]) if pairs else None

    # ---- rendering -----------------------------------------------------
    def describe_wire(self, wire: dict) -> str:
        return f"{wire.get('color', 'unknown')} wire ({wire['id']})"

    def summary_lines(self) -> list[str]:
        """Readable twin for prompts: one line per net plus unknown-hole wires."""
        lines: list[str] = []
        for c in self.twin.get("components", []):
            pins = ", ".join(f"{p['name']}@{p.get('hole') or '?'}" for p in c.get("pins", []))
            lines.append(f"{c['id']} = {c.get('part_id') or 'unknown part'} (conf {c.get('confidence', 0):.2f}): {pins}")
        for n in self.twin.get("nets", []):
            wires = ", ".join(f"{w['id']} (conf {w.get('confidence', 0):.2f})" for w in self.wires_on_net(n))
            lines.append(f"{n['id']}: {' <-> '.join(n.get('members', [])) or '(no pins)'}"
                         f" | holes {','.join(n.get('holes', []))}" + (f" | via {wires}" if wires else ""))
        return lines
