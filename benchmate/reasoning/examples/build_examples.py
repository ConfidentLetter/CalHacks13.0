"""Regenerate the few-shot bank from the mocks + rule engine. Run: python reasoning/examples/build_examples.py

Each example: {name, twin_lines, serial, question, diagnosis}. Text-only until T2's test set has photos.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from reasoning.diagnosis import build_diagnosis  # noqa: E402
from reasoning.twin_view import TwinIndex  # noqa: E402

MOCKS = ROOT / "mocks"
HERE = Path(__file__).resolve().parent


def twin(name: str) -> dict:
    return json.loads((MOCKS / f"twin_{name}.json").read_text())


def serial(name: str) -> list[str]:
    return (MOCKS / f"serial_{name}.txt").read_text().splitlines()


def missing_ground(t: dict) -> dict:
    t = copy.deepcopy(t)
    t["frame_id"] = "example_missing_ground"
    t["wires"] = [w for w in t["wires"] if w["id"] != "w_black_2"]
    t["nets"] = [n for n in t["nets"] if n["id"] != "net_1"] + [
        {"id": "net_1", "holes": ["A14", "C14", "RAIL_TOP_MINUS"], "members": ["esp32_1.GND"]},
        {"id": "net_7", "holes": ["B41"], "members": ["bme280_1.GND"]},
    ]
    return t


def unknown_part(t: dict) -> dict:
    t = copy.deepcopy(t)
    t["frame_id"] = "example_unknown_part"
    t["components"].append({"id": "unknown_1", "part_id": None, "label_text": "HW-123", "bbox": [700, 500, 60, 40],
                            "pins": [], "confidence": 0.71})
    return t


def low_conf(t: dict) -> dict:
    t = copy.deepcopy(t)
    t["frame_id"] = "example_low_confidence_wire"
    t["wires"][4]["confidence"] = 0.45
    return t


CASES = [
    ("01_ok_board", twin("ok"), serial("ok"), None),
    ("02_sda_scl_swapped", twin("sda_swapped"), serial("sda_swapped"), "Why isn't the sensor reading?"),
    ("03_vin_on_5v", twin("5v"), [], "Is it safe to power this on?"),
    ("04_missing_ground", missing_ground(twin("ok")), serial("sda_swapped"), "The sensor is not found, what's wrong?"),
    ("05_unknown_part", unknown_part(twin("ok")), serial("ok"), "Is everything wired correctly?"),
    ("06_low_confidence_wire", low_conf(twin("sda_swapped")), serial("sda_swapped"), "Why isn't the sensor reading?"),
]


def main() -> None:
    for name, t, ser, q in CASES:
        mode = "answer" if q else "proactive"
        diag = build_diagnosis(t, ser, mode=mode, question=q, stage="examples")
        ex = {"name": name.split("_", 1)[1].replace("_", " "), "frame_id": t["frame_id"],
              "twin_lines": TwinIndex(t).summary_lines(), "serial": ser, "question": q,
              "diagnosis": {k: diag[k] for k in ("findings", "needs_user_confirmation")}}
        (HERE / f"{name}.json").write_text(json.dumps(ex, indent=1))
        print("wrote", name, "->", [f["id"] for f in diag["findings"]], diag["needs_user_confirmation"])


if __name__ == "__main__":
    main()
