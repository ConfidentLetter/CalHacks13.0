"""Quick checks for Henry.  python main.py --mock   |   python main.py --image path/to/photo.jpg"""
import argparse, json
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--mock", action="store_true")
p.add_argument("--image")
a = p.parse_args()

if a.mock or not a.image:
    twin = json.loads((Path(__file__).parent / "mocks/page_twin_product_rule.json").read_text())
else:
    from transcribe import build_page_twin
    from capture.source import get_snapshot
    twin = build_page_twin(get_snapshot(f"upload:{a.image}"))

for line in sorted(twin["lines"], key=lambda l: l["order"]):
    flag = " [crossed out]" if line["status"] == "crossed_out" else ""
    print(f'{line["id"]:>3}  {line["confidence"]:.2f}  {line["latex"] or line["text"]}{flag}')
