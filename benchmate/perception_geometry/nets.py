"""Breadboard connectivity -> nets (twin.schema.json `nets`). Pure, deterministic union-find."""
from __future__ import annotations

from .board import node_of
from .telemetry import timed


def _find(parent: dict[str, str], x: str) -> str:
    parent.setdefault(x, x)
    root = x
    while parent[root] != root:
        root = parent[root]
    while parent[x] != root:          # path compression
        parent[x], x = root, parent[x]
    return root


def _union(parent: dict[str, str], a: str, b: str) -> None:
    ra, rb = _find(parent, a), _find(parent, b)
    if ra != rb:
        parent[ra] = rb


@timed("build_nets")
def build_nets(components: list[dict], wires: list[dict]) -> list[dict]:
    """Breadboard connectivity (A-E of a row, F-J of a row, each rail) -> nets per twin.schema.json.

    Only nets with at least one component pin are returned (a dangling wire alone is not a net).
    Net ids are `net_<n>`, numbered in sorted order of their members, so they are stable
    across runs for the same circuit.
    """
    parent: dict[str, str] = {}
    holes_by_node: dict[str, set[str]] = {}
    members_by_node: dict[str, list[str]] = {}

    for w in wires:
        ends = [(w.get("end_a") or {}).get("hole"), (w.get("end_b") or {}).get("hole")]
        nodes = [node_of(h) for h in ends]
        for hole, node in zip(ends, nodes):
            if node is not None:
                _find(parent, node)
                holes_by_node.setdefault(node, set()).add(hole)
        if nodes[0] is not None and nodes[1] is not None:
            _union(parent, nodes[0], nodes[1])

    for c in components:
        for pin in c.get("pins", []):
            node = node_of(pin.get("hole"))
            if node is None:
                continue
            _find(parent, node)
            holes_by_node.setdefault(node, set()).add(pin["hole"])
            members_by_node.setdefault(node, []).append(f"{c['id']}.{pin['name']}")

    groups: dict[str, dict] = {}
    for node in list(parent):
        root = _find(parent, node)
        g = groups.setdefault(root, {"holes": set(), "members": []})
        g["holes"] |= holes_by_node.get(node, set())
        g["members"] += members_by_node.get(node, [])

    nets = sorted((g for g in groups.values() if g["members"]), key=lambda g: sorted(g["members"]))
    return [
        {"id": f"net_{i + 1}", "holes": sorted(g["holes"]), "members": sorted(g["members"])}
        for i, g in enumerate(nets)
    ]
