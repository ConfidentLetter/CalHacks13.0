"""Draw a twin over its photo so hand-correcting ground truth takes a minute per image.

Usage:
    python eval/label_helper.py eval/testset/3.jpg                      # uses build_twin, writes 3.twin.json if absent
    python eval/label_helper.py eval/testset/3.jpg --twin eval/testset/3.twin.json   # draw an existing/corrected twin
Output: eval/testset/<n>.overlay.jpg (component boxes, pin holes, wire endpoints, hole labels).
Edit the .twin.json by hand, re-run, repeat until the overlay matches the photo.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from _bootstrap import REPO_ROOT  # noqa: E402,F401

COLORS = {"red": (0, 0, 255), "green": (0, 200, 0), "blue": (255, 0, 0), "yellow": (0, 220, 220),
          "orange": (0, 140, 255), "black": (30, 30, 30), "white": (240, 240, 240)}


def _hole_to_pixel(hole: str | None, H) -> tuple[float, float] | None:
    if not hole:
        return None
    try:
        from perception_geometry import hole_to_pixel  # type: ignore

        x, y = hole_to_pixel(hole, H)
        return float(x), float(y)
    except Exception:
        return None


def draw(img_path: Path, twin: dict, out: Path) -> Path:
    import cv2

    img = cv2.imread(str(img_path))
    if img is None:
        raise SystemExit(f"cannot read {img_path}")
    H = twin.get("board", {}).get("homography")
    for c in twin.get("components", []):
        x, y, w, h = [int(round(v)) for v in c["bbox"]]
        cv2.rectangle(img, (x, y), (x + w, y + h), (255, 0, 255), 2)
        cv2.putText(img, f"{c['id']} ({c.get('part_id')})", (x, max(12, y - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 255), 1, cv2.LINE_AA)
        for p in c.get("pins", []):
            px = _hole_to_pixel(p.get("hole"), H)
            if px:
                cv2.circle(img, (int(px[0]), int(px[1])), 5, (255, 0, 255), 1)
                cv2.putText(img, f"{p['name']}@{p['hole']}", (int(px[0]) + 6, int(px[1]) + 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 0, 255), 1, cv2.LINE_AA)
    for w in twin.get("wires", []):
        col = COLORS.get(w.get("color", ""), (200, 200, 200))
        ends = []
        for end in ("end_a", "end_b"):
            e = w.get(end) or {}
            px = e.get("pixel")
            if not px or px == [0, 0]:
                px = _hole_to_pixel(e.get("hole"), H)
            if px:
                ends.append((int(px[0]), int(px[1])))
                cv2.circle(img, ends[-1], 6, col, 2)
                cv2.putText(img, str(e.get("hole")), (ends[-1][0] + 6, ends[-1][1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.4, col, 1, cv2.LINE_AA)
        if len(ends) == 2:
            cv2.line(img, ends[0], ends[1], col, 1, cv2.LINE_AA)
    cv2.imwrite(str(out), img)
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image", type=Path)
    ap.add_argument("--twin", type=Path, help="twin json to draw (default: <n>.twin.json, created via build_twin)")
    args = ap.parse_args(argv)

    stem = args.image.name.rsplit(".", 1)[0]
    twin_path = args.twin or args.image.with_name(f"{stem}.twin.json")
    if twin_path.is_file():
        twin = json.loads(twin_path.read_text())
    else:
        from perception_detect import build_twin

        from perception_detect.registration import load_registrations

        twin = build_twin(str(args.image))
        twin.setdefault("expected_findings", [])
        twin.setdefault("serial", [])
        twin.setdefault("registrations", [{k: r.get(k) for k in ("part_id", "row_index", "pixel", "end_pixel")}
                                          for r in load_registrations()])
        twin_path.write_text(json.dumps(twin, indent=2))
        print("wrote draft ground truth", twin_path, "- correct it by hand")
    out = draw(args.image, twin, args.image.with_name(f"{stem}.overlay.jpg"))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
