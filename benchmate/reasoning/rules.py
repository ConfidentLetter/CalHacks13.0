"""Rule engine: deterministic profile checks over a twin. No I/O, no model.

Each check `kind` from contracts/profile.example.yaml is a pure function returning a finding
dict (diagnosis.schema.json shape) with an extra `_meta` key for downstream stages
(citations, confirmation prompts). `strip_meta()` removes it before the diagnosis leaves T3.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, NamedTuple

from reasoning.profiles import load_profiles, profile_for
from reasoning.twin_view import TwinIndex


@dataclass(frozen=True)
class Bound:
    """A twin component bound to its profile."""
    component: dict[str, Any]
    profile: dict[str, Any]

    @property
    def id(self) -> str:
        return self.component["id"]

    @property
    def part_id(self) -> str:
        return self.profile.get("part_id") or (self.component.get("part_id") or "unknown")


class Resolution(NamedTuple):
    mcu: Bound | None
    peripherals: list[Bound]
    unknown: list[dict[str, Any]]


class RuleResult(NamedTuple):
    findings: list[dict[str, Any]]
    confirmations: list[dict[str, str]]


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------
def resolve(twin: dict[str, Any], profiles: dict[str, dict[str, Any]]) -> Resolution:
    mcus: list[Bound] = []
    peripherals: list[Bound] = []
    unknown: list[dict[str, Any]] = []
    for comp in twin.get("components", []):
        prof = profile_for(comp.get("part_id"), profiles)
        if prof is None:
            unknown.append(comp)
        elif prof.get("role") == "mcu":
            mcus.append(Bound(comp, prof))
        else:
            peripherals.append(Bound(comp, prof))
    mcu = max(mcus, key=lambda b: b.component.get("confidence", 0), default=None)
    return Resolution(mcu, peripherals, unknown)


# ---------------------------------------------------------------------------
# finding construction
# ---------------------------------------------------------------------------
def make_finding(
    idx: TwinIndex, *, id: str, severity: str, title: str, explanation: str, fix: str,
    wires: list[str], components: list[str], meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    depends = list(dict.fromkeys(wires + components))
    return {
        "id": id,
        "severity": severity,
        "title": title,
        "explanation": explanation,
        "fix": fix,
        "evidence": {"wires": list(dict.fromkeys(wires)), "components": list(dict.fromkeys(components))},
        "confidence": idx.min_confidence(depends),
        "_meta": {"depends_on": depends, **(meta or {})},
    }


def strip_meta(finding: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in finding.items() if k != "_meta"}


def _move_fix(idx: TwinIndex, periph: Bound, pin: str, target_hole: str | None, target_label: str) -> tuple[str, list[str], dict]:
    """'Move the yellow wire from I18 to I15' or, with no wire found, 'Add a wire ...'."""
    hit = idx.wire_at_pin(periph.id, pin)
    if hit is None:
        src = idx.pin_hole(periph.id, pin) or f"{periph.id}.{pin}"
        dest = target_hole or target_label
        return f"Add a wire from {src} to {dest} ({target_label})", [], {"far_hole": None, "target_hole": target_hole}
    wire, far = hit
    dest = target_hole or target_label
    fix = f"Move the {wire.get('color', '')} wire from {far or 'its far end'} to {dest}".replace("  ", " ")
    return fix, [wire["id"]], {"wire_id": wire["id"], "far_hole": far, "target_hole": target_hole}


# ---------------------------------------------------------------------------
# check kinds
# ---------------------------------------------------------------------------
def check_same_net(idx: TwinIndex, periph: Bound, mcu: Bound, check: dict[str, Any]) -> dict[str, Any] | None:
    pin, role = check.get("pin"), check.get("target_role")
    target_pin = (mcu.profile.get("roles") or {}).get(role)
    if not pin or not target_pin:
        return None
    net = idx.net_of(periph.id, pin)
    if net and f"{mcu.id}.{target_pin}" in net.get("members", []):
        return None
    actual = idx.pins_of(mcu.id, net)
    target_hole = idx.best_hole_on_net_of(mcu.id, target_pin)
    fix, wire_ids, fix_meta = _move_fix(idx, periph, pin, target_hole, f"{mcu.id} {target_pin}")
    if not wire_ids:
        wire_ids = [w["id"] for w in idx.wires_on_net(net)]
    if actual:
        title = f"{pin} is on {actual[0]}, should be {target_pin}"
        where = f"lands on {mcu.id} {', '.join(actual)}"
    else:
        title = f"{pin} is not connected to {target_pin}"
        where = "does not reach the microcontroller" if net else "is not connected to anything"
    wire_txt = f" ({idx.describe_wire(idx.wires[wire_ids[0]])})" if wire_ids and wire_ids[0] in idx.wires else ""
    explanation = (f"{periph.id} {pin}{wire_txt} {where}. The {mcu.part_id} profile expects "
                   f"{role} on {target_pin}.")
    return make_finding(
        idx, id=check["id"], severity=check.get("severity", "error"), title=title,
        explanation=explanation, fix=fix, wires=wire_ids, components=[periph.id, mcu.id],
        meta={"kind": "same_net", "check_id": check["id"], "part_id": periph.part_id, "pin": pin,
              "target_role": role, "target_pin": target_pin, "actual_pins": actual,
              "search_query": check.get("search_query"), "question": check.get("question"),
              "key_terms": [pin, target_pin], **fix_meta},
    )


def _sources_on_net(idx: TwinIndex, mcu: Bound, net: dict | None) -> list[tuple[str, float]]:
    sources = mcu.profile.get("sources") or {}
    return [(p, float(sources[p])) for p in idx.pins_of(mcu.id, net) if p in sources]


def _safe_source(mcu: Bound, max_v: float) -> str | None:
    """Highest-voltage MCU source that stays within max_v."""
    ok = [(p, float(v)) for p, v in (mcu.profile.get("sources") or {}).items() if float(v) <= max_v]
    return max(ok, key=lambda pv: pv[1])[0] if ok else None


def check_max_supply(idx: TwinIndex, periph: Bound, mcu: Bound, check: dict[str, Any]) -> dict[str, Any] | None:
    pin = check.get("pin")
    supply = periph.profile.get("supply") or {}
    max_v = supply.get("max_v")
    if not pin or max_v is None:
        return None
    max_v = float(max_v)
    net = idx.net_of(periph.id, pin)
    sources = _sources_on_net(idx, mcu, net)
    safe = _safe_source(mcu, max_v)
    target_hole = idx.best_hole_on_net_of(mcu.id, safe) if safe else None
    common = {"kind": "max_supply", "check_id": check["id"], "part_id": periph.part_id, "pin": pin,
              "max_v": max_v, "search_query": check.get("search_query"), "question": check.get("question"),
              "key_terms": [f"{max_v:g}", "3.6", "VDD"], "safe_source": safe}
    over = [(p, v) for p, v in sources if v > max_v]
    if over:
        src, volts = over[0]
        fix, wire_ids, fix_meta = _move_fix(idx, periph, pin, target_hole, f"{mcu.id} {safe or 'a lower rail'}")
        if not wire_ids:
            wire_ids = [w["id"] for w in idx.wires_on_net(net)]
        return make_finding(
            idx, id=check["id"], severity=check.get("severity", "error"),
            title=f"{pin} is on {src}, max is {max_v:g} V",
            explanation=(f"{periph.id} {pin} is powered from {mcu.id} {src} ({volts:g} V). "
                         f"The {periph.part_id} datasheet limits the supply to {max_v:g} V, so this can damage it."),
            fix=fix, wires=wire_ids, components=[periph.id, mcu.id],
            meta={**common, "source_pin": src, "source_v": volts, **fix_meta},
        )
    if not sources:
        fix, wire_ids, fix_meta = _move_fix(idx, periph, pin, target_hole, f"{mcu.id} {safe or 'a power pin'}")
        if not wire_ids:
            wire_ids = [w["id"] for w in idx.wires_on_net(net)]
        return make_finding(
            idx, id=check["id"], severity="warning", title=f"{pin} is not powered",
            explanation=f"No power pin of {mcu.id} is on the net of {periph.id} {pin}.",
            fix=fix, wires=wire_ids, components=[periph.id, mcu.id],
            meta={**common, "source_pin": None, **fix_meta},
        )
    return None


CHECKS = {"same_net": check_same_net, "max_supply": check_max_supply}


# ---------------------------------------------------------------------------
# patterns on top of single checks
# ---------------------------------------------------------------------------
def _merge_i2c_swap(idx: TwinIndex, findings: list[dict[str, Any]], mcu: Bound) -> list[dict[str, Any]]:
    roles = mcu.profile.get("roles") or {}
    sda_pin, scl_pin = roles.get("i2c_sda"), roles.get("i2c_scl")
    by_comp: dict[str, dict[str, dict]] = {}
    for f in findings:
        m = f["_meta"]
        if m.get("target_role") in ("i2c_sda", "i2c_scl"):
            by_comp.setdefault(f["evidence"]["components"][0], {})[m["target_role"]] = f
    out = list(findings)
    for comp_id, pair in by_comp.items():
        sda, scl = pair.get("i2c_sda"), pair.get("i2c_scl")
        if not (sda and scl and scl_pin in sda["_meta"]["actual_pins"] and sda_pin in scl["_meta"]["actual_pins"]):
            continue
        sda_w, scl_w = sda["_meta"].get("wire_id"), scl["_meta"].get("wire_id")
        if sda_w and scl_w:
            fix = (f"Swap the {idx.wires[sda_w]['color']} wire ({sda['_meta']['far_hole']}) and the "
                   f"{idx.wires[scl_w]['color']} wire ({scl['_meta']['far_hole']})")
        else:
            fix = f"Swap the wires on {mcu.id} {sda_pin} and {scl_pin}"
        wires = [w for w in (sda_w, scl_w) if w] or sda["evidence"]["wires"] + scl["evidence"]["wires"]
        merged = make_finding(
            idx, id="i2c_swapped", severity="error", title="SDA and SCL are swapped",
            explanation=(f"{comp_id} SDA lands on {mcu.id} {scl_pin} and SCL on {sda_pin}. "
                         f"The {mcu.part_id} default I2C pins are SDA={sda_pin}, SCL={scl_pin}, "
                         "so the bus scan finds no device."),
            fix=fix, wires=wires, components=[comp_id, mcu.id],
            meta={**sda["_meta"], "kind": "pattern", "check_id": "i2c_swapped", "key_terms": ["SDA", "SCL"],
                  "sda_far": sda["_meta"].get("far_hole"), "scl_far": scl["_meta"].get("far_hole"),
                  "question": "Which board pins do the SDA and SCL wires end at?"},
        )
        out = [merged if f is sda else f for f in out if f is not scl]
    return out


def _shorted_sources(idx: TwinIndex, peripherals: list[Bound], mcu: Bound) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for periph in peripherals:
        for p in periph.component.get("pins", []):
            net = idx.net_of(periph.id, p["name"])
            if not net or net["id"] in seen:
                continue
            sources = _sources_on_net(idx, mcu, net)
            if len({s for s, _ in sources}) < 2:
                continue
            seen.add(net["id"])
            max_v = float((periph.profile.get("supply") or {}).get("max_v", 1e9))
            culprit = max(sources, key=lambda sv: (sv[1] > max_v, sv[1]))[0]
            hit = idx.wire_at_pin(mcu.id, culprit)
            names = " and ".join(s for s, _ in sources)
            if hit:
                w, far = hit
                fix = f"Remove the {w.get('color', '')} wire between {idx.pin_hole(mcu.id, culprit)} and {far}"
                wires = [w["id"]]
            else:
                fix = f"Remove the wire joining {names}"
                wires = [w["id"] for w in idx.wires_on_net(net)]
            out.append(make_finding(
                idx, id=f"sources_shorted:{net['id']}", severity="error", title=f"{names} are shorted together",
                explanation=f"{mcu.id} pins {names} are on the same net ({net['id']}) through {periph.id} {p['name']}.",
                fix=fix, wires=wires, components=[periph.id, mcu.id],
                meta={"kind": "pattern", "check_id": "sources_shorted", "part_id": mcu.part_id,
                      "search_query": "power supply pins", "key_terms": [names], "net_id": net["id"]},
            ))
    return out


# ---------------------------------------------------------------------------
# entry point
# ---------------------------------------------------------------------------
def _unknown_part_finding(idx: TwinIndex, comp: dict[str, Any]) -> dict[str, Any]:
    label = comp.get("label_text") or comp.get("part_id") or comp["id"]
    return make_finding(
        idx, id=f"unknown_part:{comp['id']}", severity="info", title="Unknown part - register it to check it",
        explanation=f"{comp['id']} ('{label}') has no profile, so its wiring cannot be checked.",
        fix=f"Click the first pin of {comp['id']} to register it", wires=[], components=[comp["id"]],
        meta={"kind": "unknown_part", "check_id": "unknown_part", "part_id": comp.get("part_id")},
    )


def _dedupe_ids(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: dict[str, int] = {}
    for f in findings:
        counts[f["id"]] = counts.get(f["id"], 0) + 1
    seen: dict[str, int] = {}
    out = []
    for f in findings:
        if counts[f["id"]] == 1:
            out.append(f)
            continue
        seen[f["id"]] = seen.get(f["id"], 0) + 1
        comp = (f["evidence"]["components"] or ["x"])[0]
        out.append({**f, "id": f["id"] if seen[f["id"]] == 1 else f"{f['id']}:{comp}"})
    return out


def run_rules(twin: dict[str, Any], profiles: dict[str, dict[str, Any]] | None = None) -> RuleResult:
    """All deterministic findings for a twin, plus confirmation prompts for pins we could not place."""
    idx = TwinIndex(twin)
    res = resolve(twin, profiles if profiles is not None else load_profiles())
    findings: list[dict[str, Any]] = [_unknown_part_finding(idx, c) for c in res.unknown]
    confirmations: list[dict[str, str]] = []
    if res.mcu is None:
        if res.peripherals:
            findings.append(make_finding(
                idx, id="no_mcu", severity="warning", title="No microcontroller recognised",
                explanation="No component on the board has an MCU profile, so bus and power checks cannot run.",
                fix="Register the microcontroller by clicking its first pin",
                wires=[], components=[p.id for p in res.peripherals],
                meta={"kind": "no_mcu", "check_id": "no_mcu"}))
        return RuleResult(findings, confirmations)
    for periph in res.peripherals:
        for check in periph.profile.get("checks") or []:
            fn = CHECKS.get(check.get("kind"))
            if fn is None or not check.get("pin"):
                continue
            if idx.pin_hole(periph.id, check["pin"]) is None:
                confirmations.append({"element_id": periph.id,
                                      "prompt": f"Which hole is {periph.id}'s {check['pin']} pin in?"})
                continue
            f = fn(idx, periph, res.mcu, check)
            if f is not None:
                findings.append(f)
    findings = _merge_i2c_swap(idx, findings, res.mcu)
    findings += _shorted_sources(idx, res.peripherals, res.mcu)
    order = {"error": 0, "warning": 1, "info": 2, "ok": 3}
    findings = sorted(_dedupe_ids(findings), key=lambda f: (order.get(f["severity"], 9), -f["confidence"]))
    uniq = {(c["element_id"], c["prompt"]): c for c in confirmations}
    return RuleResult(findings, list(uniq.values()))
