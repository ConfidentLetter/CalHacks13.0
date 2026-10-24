"""Pure metric functions for comparing a predicted twin with a ground-truth twin.

All functions are deterministic and side-effect free so they can be unit-tested on mocks.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Ratio:
    hits: int
    total: int

    @property
    def value(self) -> float | None:
        return None if self.total == 0 else self.hits / self.total

    def __add__(self, other: "Ratio") -> "Ratio":
        return Ratio(self.hits + other.hits, self.total + other.total)


def _pin_map(component: dict) -> frozenset[tuple[str, str | None]]:
    return frozenset((p["name"], p.get("hole")) for p in component.get("pins", []))


def component_matches(gt: dict, pred: dict) -> bool:
    """Right part_id and every ground-truth pin in the right hole."""
    if gt.get("part_id") != pred.get("part_id"):
        return False
    return _pin_map(gt) <= _pin_map(pred)


def component_accuracy(gt_twin: dict, pred_twin: dict) -> Ratio:
    """Fraction of ground-truth components found with the right part_id and every pin in the right hole."""
    preds = list(pred_twin.get("components", []))
    hits = 0
    for gt in gt_twin.get("components", []):
        idx = next((i for i, p in enumerate(preds) if component_matches(gt, p)), None)
        if idx is not None:
            hits += 1
            preds.pop(idx)
    return Ratio(hits, len(gt_twin.get("components", [])))


def _ends(wire: dict) -> tuple[str | None, str | None]:
    return ((wire.get("end_a") or {}).get("hole"), (wire.get("end_b") or {}).get("hole"))


def _matching_ends(gt: tuple, pred: tuple) -> int:
    """How many of the GT wire's two ends the predicted wire reproduces (either orientation)."""
    straight = sum(1 for a, b in zip(gt, pred) if a is not None and a == b)
    flipped = sum(1 for a, b in zip(gt, pred[::-1]) if a is not None and a == b)
    return max(straight, flipped)


def wire_endpoint_accuracy(gt_twin: dict, pred_twin: dict) -> Ratio:
    """Fraction of ground-truth wire endpoints with the exact hole. Wires are matched one-to-one
    (greedy, best match first) so two wires with swapped ends do not score as correct.
    GT endpoints whose hole is None count in the denominator and can never be hit."""
    gts = [_ends(w) for w in gt_twin.get("wires", [])]
    preds = [_ends(w) for w in pred_twin.get("wires", [])]
    total = 2 * len(gts)
    hits = 0
    remaining = list(preds)
    for g in sorted(gts, key=lambda e: -sum(x is not None for x in e)):
        best_i, best = None, 0
        for i, pr in enumerate(remaining):
            m = _matching_ends(g, pr)
            if m > best:
                best_i, best = i, m
        if best_i is not None:
            hits += best
            remaining.pop(best_i)
    return Ratio(hits, total)


def extra_components(gt_twin: dict, pred_twin: dict) -> int:
    """Predicted components that match no ground-truth component (false positives / duplicates)."""
    preds = list(pred_twin.get("components", []))
    for gt in gt_twin.get("components", []):
        idx = next((i for i, p in enumerate(preds) if component_matches(gt, p)), None)
        if idx is not None:
            preds.pop(idx)
    return len(preds)


def net_groups(twin: dict) -> frozenset[frozenset[str]]:
    """Nets as a set of member groups; nets with < 2 members carry no connectivity and are ignored."""
    return frozenset(frozenset(n.get("members", [])) for n in twin.get("nets", [])
                     if len(n.get("members", [])) >= 2)


def nets_equal(gt_twin: dict, pred_twin: dict) -> bool:
    return net_groups(gt_twin) == net_groups(pred_twin)


def finding_ids(diagnosis: dict) -> frozenset[str]:
    """Ids of findings that the user would be shown (error/warning); 'ok'/'info' are not failures."""
    return frozenset(f["id"] for f in diagnosis.get("findings", [])
                     if f.get("severity") in ("error", "warning"))


def diagnosis_equal(expected_findings: list[str] | None, diagnosis: dict | None,
                    *, failed: bool = False) -> bool | None:
    """None when the image has no expected_findings or T3 is not available; False when the twin or
    the checks crashed (a crash is a miss, not an excuse)."""
    if expected_findings is None:
        return None
    if failed:
        return False
    if diagnosis is None:
        return None
    return frozenset(expected_findings) == finding_ids(diagnosis)


def percentile(values: list[float], q: float) -> float | None:
    """Nearest-rank percentile, q in [0, 100]: the ceil(q/100 * n)-th smallest value."""
    if not values:
        return None
    s = sorted(values)
    k = max(1, min(len(s), math.ceil(q / 100.0 * len(s))))
    return s[k - 1]


def fmt(v: float | None, nd: int = 3) -> str:
    return "" if v is None else f"{v:.{nd}f}"
