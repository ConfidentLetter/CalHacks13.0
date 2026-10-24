"""Serial-log evidence: match recent lines against the regex table in config."""
from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

from reasoning.config import I2C_CHECK_IDS, SERIAL_PATTERNS, SERIAL_WINDOW_LINES


@lru_cache(maxsize=None)
def _compiled() -> dict[str, re.Pattern[str]]:
    return {name: re.compile(pat, re.IGNORECASE) for name, pat in SERIAL_PATTERNS.items()}


def classify(serial: list[str] | None) -> dict[str, list[str]]:
    """name -> matching lines (most recent SERIAL_WINDOW_LINES only, order preserved)."""
    lines = [str(l).strip() for l in (serial or []) if str(l).strip()][-SERIAL_WINDOW_LINES:]
    return {name: [l for l in lines if rx.search(l)] for name, rx in _compiled().items()}


def is_i2c_finding(finding: dict[str, Any]) -> bool:
    meta = finding.get("_meta", {})
    return finding["id"] in I2C_CHECK_IDS or meta.get("check_id") in I2C_CHECK_IDS or \
        str(meta.get("target_role", "")).startswith("i2c_")


def attach_serial(findings: list[dict[str, Any]], evidence: dict[str, list[str]]) -> list[dict[str, Any]]:
    """Return new findings with matching serial lines attached as evidence."""
    fails = evidence.get("i2c_fail", [])
    if not fails:
        return findings
    out = []
    for f in findings:
        if is_i2c_finding(f):
            out.append({**f, "evidence": {**f["evidence"], "serial_lines": fails[-3:]}})
        else:
            out.append(f)
    return out


def sensor_ok_finding(evidence: dict[str, list[str]], peripheral_ids: list[str]) -> dict[str, Any] | None:
    """An `ok` card when serial shows a live reading and nothing is wrong."""
    oks = evidence.get("i2c_ok", [])
    if not oks or evidence.get("i2c_fail"):
        return None
    return {
        "id": "sensor_responding", "severity": "ok", "title": "Sensor responding",
        "explanation": f"Serial shows a live reading: {oks[-1]}",
        "fix": "Nothing to do",
        "evidence": {"wires": [], "components": peripheral_ids, "serial_lines": oks[-3:]},
        "confidence": 0.95,
        "_meta": {"kind": "serial", "check_id": "sensor_responding", "depends_on": []},
    }


def serial_only_i2c_finding(evidence: dict[str, list[str]], peripheral_ids: list[str]) -> dict[str, Any] | None:
    """Serial says the bus is empty but the rules found nothing: hedge with a warning."""
    fails = evidence.get("i2c_fail", [])
    if not fails:
        return None
    return {
        "id": "i2c_no_device", "severity": "warning", "title": "No I2C device found on the bus",
        "explanation": ("The microcontroller reports an empty I2C bus but the image shows the expected wiring. "
                        "A wire may not be seated, or the camera may have mis-read a wire end."),
        "fix": "Reseat the SDA, SCL and VIN wires, then rescan",
        "evidence": {"wires": [], "components": peripheral_ids, "serial_lines": fails[-3:]},
        "confidence": 0.6,
        "_meta": {"kind": "serial", "check_id": "i2c_no_device", "depends_on": []},
    }
