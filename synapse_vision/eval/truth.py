"""Ground-truth file format for eval/testset/<n>.truth.json and the helpers that read/write it.

A truth file is a trimmed page twin plus per-line labelling fields:

    {"image": "eval/testset/3.jpg", "dewarped_path": "runtime/dewarped/x.jpg", "width": 1700, "height": 2200,
     "source_snapshot_id": "snap_...", "reviewed": false, "note": "",
     "lines": [{"id": "L0", "order": 0, "bbox": [x, y, w, h], "status": "active", "latex": "...", "text": "...",
                "planted_error": false, "planted_note": "", "corrected_latex": ""}]}

`corrected_latex` is what the line WOULD say if the student had not made the planted mistake. The
planted-error-preservation metric checks the system's reading is NOT equivalent to it.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTSET_DIR = ROOT / "eval" / "testset"
IMAGE_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp")
STATUSES = ("active", "crossed_out", "illegible")
_SAFE_NAME = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def page_names(testset_dir: Path | None = None) -> list[str]:
    """Stems of the photos in the test set, numerically sorted where possible."""
    testset_dir = Path(testset_dir) if testset_dir else TESTSET_DIR
    if not testset_dir.exists():
        return []
    names = {p.stem for p in testset_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS and not p.stem.endswith(".truth")}

    def key(n: str):
        m = re.match(r"^(\d+)(.*)$", n)
        return (0, int(m.group(1)), m.group(2)) if m else (1, 0, n)

    return sorted(names, key=key)


def image_path(name: str, testset_dir: Path | None = None) -> Path | None:
    testset_dir = Path(testset_dir) if testset_dir else TESTSET_DIR
    for ext in IMAGE_EXTS:
        p = testset_dir / f"{name}{ext}"
        if p.exists():
            return p
    return None


def truth_path(name: str, testset_dir: Path | None = None) -> Path:
    testset_dir = Path(testset_dir) if testset_dir else TESTSET_DIR
    if not _SAFE_NAME.match(name):
        raise ValueError(f"bad page name {name!r}")
    return testset_dir / f"{name}.truth.json"


def load_truth(name: str, testset_dir: Path | None = None) -> dict | None:
    testset_dir = Path(testset_dir) if testset_dir else TESTSET_DIR
    p = truth_path(name, testset_dir)
    if not p.exists():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def save_truth(name: str, truth: dict, testset_dir: Path | None = None) -> Path:
    testset_dir = Path(testset_dir) if testset_dir else TESTSET_DIR
    errors = validate_truth(truth)
    if errors:
        raise ValueError("invalid truth: " + "; ".join(errors))
    p = truth_path(name, testset_dir)
    p.write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def validate_truth(truth: dict) -> list[str]:
    """Cheap structural validation (no jsonschema dependency needed for a local tool)."""
    errs: list[str] = []
    if not isinstance(truth, dict):
        return ["truth must be an object"]
    for key in ("image", "width", "height", "lines"):
        if key not in truth:
            errs.append(f"missing {key}")
    if not isinstance(truth.get("lines"), list):
        return errs + ["lines must be a list"]
    for i, line in enumerate(truth["lines"]):
        bbox = line.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4 and all(isinstance(v, (int, float)) for v in bbox)):
            errs.append(f"lines[{i}].bbox must be [x, y, w, h]")
        if line.get("status") not in STATUSES:
            errs.append(f"lines[{i}].status must be one of {STATUSES}")
        if not isinstance(line.get("latex", ""), str):
            errs.append(f"lines[{i}].latex must be a string")
        if line.get("planted_error") and not line.get("corrected_latex"):
            errs.append(f"lines[{i}] is planted_error but has no corrected_latex")
    return errs


def truth_from_twin(twin: dict, image: str) -> dict:
    """Pre-label: strip a page twin down to the editable truth shape (all planted flags off)."""
    lines = []
    for i, l in enumerate(sorted(twin.get("lines", []), key=lambda x: x.get("order", 0))):
        lines.append({
            "id": l.get("id", f"L{i}"), "order": i, "bbox": [float(v) for v in l["bbox"]],
            "status": l.get("status", "active"), "latex": l.get("latex", ""), "text": l.get("text", ""),
            "confidence_at_prelabel": l.get("confidence"),
            "planted_error": False, "planted_note": "", "corrected_latex": "",
        })
    img = twin.get("image", {})
    return {
        "image": image, "dewarped_path": img.get("dewarped_path", ""), "width": int(img.get("width", 0)),
        "height": int(img.get("height", 0)), "source_snapshot_id": twin.get("snapshot_id"),
        "quality": twin.get("quality", {}), "reviewed": False, "note": "", "lines": lines,
    }


def rel(p: Path) -> str:
    """Repo-relative string when inside the repo, else absolute."""
    try:
        return str(Path(p).resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(Path(p).resolve())


def new_line(order: int, bbox: list[float]) -> dict:
    return {"id": f"T{order}", "order": order, "bbox": [float(v) for v in bbox], "status": "active", "latex": "",
            "text": "", "planted_error": False, "planted_note": "", "corrected_latex": ""}
