"""Integration entry point. Owned by the integrator.

Until real modules land, run with mocks:  python main.py --mock
"""
import argparse
import json
from pathlib import Path

MOCKS = Path(__file__).parent / "mocks"


def run_mock(scenario: str) -> None:
    twin = json.loads((MOCKS / f"twin_{scenario}.json").read_text())
    print("twin nets:", [n["members"] for n in twin["nets"]])
    if scenario == "sda_swapped":
        print("diagnosis:", json.loads((MOCKS / "diagnosis_sda_swapped.json").read_text())["findings"][0]["title"])


def run_real(question: str | None) -> None:
    from app import capture, serial_bridge
    from perception_detect import build_twin
    from reasoning import run_checks, answer

    frame = capture.get_frame(high_res=True)
    twin = build_twin(frame)
    serial = serial_bridge.get_recent_serial(10)
    result = answer(question, twin, serial, frame) if question else run_checks(twin, serial)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mock", choices=["ok", "sda_swapped", "5v"])
    p.add_argument("--ask")
    a = p.parse_args()
    run_mock(a.mock) if a.mock else run_real(a.ask)
