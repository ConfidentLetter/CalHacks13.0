"""Live smoke test for refine(). Needs ANTHROPIC_API_KEY (source env.sh). No tests import this.

    python -m reasoning.smoke_refine [sda_swapped|5v|ok] [frame.jpg]

Prints the Phase 1 (rules) card, then the Phase 2 (model) card and latencies.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import reasoning
from reasoning.config import ROOT, model_name, offline

QUESTIONS = {"sda_swapped": "Why isn't the sensor reading?", "5v": "Is it safe to power this on?", "ok": "Is everything wired correctly?"}


def main() -> int:
    scenario = sys.argv[1] if len(sys.argv) > 1 else "sda_swapped"
    frame = sys.argv[2] if len(sys.argv) > 2 else str(ROOT / "runtime" / "frames" / "latest.jpg")
    twin = json.loads((ROOT / "mocks" / f"twin_{scenario}.json").read_text())
    serial_file = ROOT / "mocks" / ("serial_ok.txt" if scenario == "ok" else "serial_sda_swapped.txt")
    serial = serial_file.read_text().splitlines()
    q = QUESTIONS[scenario]
    print(f"model={model_name()} offline={offline()} frame_exists={Path(frame).is_file()}")
    rules = reasoning.answer(q, twin, serial, frame)
    print("\n== Phase 1 (rules) ==")
    for f in rules["findings"]:
        print(f"[{f['severity']}] {f['title']} -- {f['fix']}  (conf {f['confidence']})")
    print("latency_ms:", rules["latency_ms"])
    refined = reasoning.refine(q, twin, serial, frame, rules)
    print("\n== Phase 2 (model) ==", "(unchanged: fell back to rules)" if refined is rules else "")
    for f in refined["findings"]:
        print(f"[{f['severity']}] {f['title']} -- {f['fix']}  (conf {f['confidence']})")
        print("   ", f["explanation"])
        for c in f["evidence"].get("datasheet", []):
            print(f"    cite {c['part_id']} p.{c['page']}: {c.get('quote', '')[:120]}")
    print("needs_user_confirmation:", refined["needs_user_confirmation"])
    print("latency_ms:", refined["latency_ms"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
