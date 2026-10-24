"""Run build_twin over eval/testset and append one accuracy row to eval/history.csv.

Usage:
    python eval/run_eval.py --note "what changed since the last row"
    python eval/run_eval.py --note "mock baseline" --dry-run     # compute, do not append

Test set layout (see eval/testset/README.md):
    eval/testset/<n>.jpg          photo from the fixed mount
    eval/testset/<n>.twin.json    hand-corrected ground truth (twin.schema.json + optional
                                  "expected_findings": ["supply_voltage", ...] and "serial": [...])
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

from _bootstrap import HISTORY_COLUMNS, HISTORY_CSV, LAST_RUN_JSON, TESTSET_DIR  # noqa: E402

import metrics as M  # noqa: E402


def list_cases(testset: Path) -> list[tuple[Path, Path]]:
    cases = []
    for gt in sorted(testset.glob("*.twin.json")):
        stem = gt.name[: -len(".twin.json")]
        for ext in (".jpg", ".jpeg", ".png"):
            img = testset / f"{stem}{ext}"
            if img.is_file():
                cases.append((img, gt))
                break
    return cases


def _run_checks(twin: dict, serial: list[str]) -> tuple[dict | None, bool]:
    """(diagnosis, crashed). (None, False) when T3 is not importable yet."""
    try:
        from reasoning import run_checks  # type: ignore
    except Exception:
        return None, False
    try:
        return run_checks(twin, serial), False
    except Exception:
        traceback.print_exc()
        return None, True


def _apply_registrations(gt: dict) -> None:
    """Ground-truth files may carry the click registrations the photo was taken with, so the eval
    is self-contained and never depends on (or pollutes) the live demo's runtime/registrations.json."""
    from perception_detect.registration import clear_registrations, register, set_current_homography

    clear_registrations()
    regs = gt.get("registrations") or []
    if not regs:
        return
    set_current_homography(gt.get("board", {}).get("homography"), calibrated=True)
    for r in regs:
        register(r["part_id"], int(r["row_index"]), tuple(r["pixel"]),
                 end_pixel=tuple(r["end_pixel"]) if r.get("end_pixel") else None)


def evaluate_case(img: Path, gt_path: Path, build_twin) -> dict:
    gt = json.loads(gt_path.read_text())
    error = None
    try:
        _apply_registrations(gt)
    except Exception as exc:
        error = f"registrations: {type(exc).__name__}: {exc}"
    t0 = time.perf_counter()
    try:
        pred = build_twin(str(img))
    except Exception as exc:  # the eval must keep going
        pred = {"components": [], "wires": [], "nets": []}
        error = error or f"{type(exc).__name__}: {exc}"
    ms = (time.perf_counter() - t0) * 1000.0
    diag, crashed = _run_checks(pred, gt.get("serial", [])) if error is None else (None, True)
    return {
        "image": img.name,
        "error": error,
        "ms": ms,
        "component": M.component_accuracy(gt, pred),
        "extra_components": M.extra_components(gt, pred),
        "wire": M.wire_endpoint_accuracy(gt, pred),
        "nets_equal": M.nets_equal(gt, pred),
        "diagnosis_equal": M.diagnosis_equal(gt.get("expected_findings"), diag, failed=crashed),
        "predicted_findings": sorted(M.finding_ids(diag)) if diag else None,
    }


def summarize(results: list[dict]) -> dict:
    comp = sum((r["component"] for r in results), M.Ratio(0, 0))
    wire = sum((r["wire"] for r in results), M.Ratio(0, 0))
    net = M.Ratio(sum(1 for r in results if r["nets_equal"]), len(results))
    diag_cases = [r for r in results if r["diagnosis_equal"] is not None]
    diag = M.Ratio(sum(1 for r in diag_cases if r["diagnosis_equal"]), len(diag_cases))
    lat = [r["ms"] for r in results]
    return {
        "n": len(results),
        "component_acc": comp.value, "wire_acc": wire.value, "net_acc": net.value,
        "diagnosis_acc": diag.value,
        "median_ms": M.percentile(lat, 50), "p90_ms": M.percentile(lat, 90),
    }


def append_history(summary: dict, note: str, path: Path = HISTORY_CSV) -> None:
    new = not path.is_file() or path.stat().st_size == 0
    with path.open("a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(HISTORY_COLUMNS)
        w.writerow([
            datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"), note,
            M.fmt(summary["component_acc"]), M.fmt(summary["wire_acc"]), M.fmt(summary["net_acc"]),
            M.fmt(summary["diagnosis_acc"]), M.fmt(summary["median_ms"], 0), M.fmt(summary["p90_ms"], 0),
        ])


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--note", required=True, help="short description of what changed since the last row")
    ap.add_argument("--testset", type=Path, default=TESTSET_DIR)
    ap.add_argument("--dry-run", action="store_true", help="compute but do not append to history.csv")
    args = ap.parse_args(argv)

    import os
    import tempfile

    # isolate from the live demo: own runtime dir (telemetry + registrations), twin cache cleared
    os.environ["BM_RUNTIME_DIR"] = tempfile.mkdtemp(prefix="bm_eval_")
    from perception_detect import build_twin  # noqa: E402  (after _bootstrap)
    from perception_detect.twin import clear_cache

    clear_cache()
    cases = list_cases(args.testset)
    if not cases:
        print(f"no cases in {args.testset} (need <n>.jpg + <n>.twin.json). See eval/testset/README.md")
        return 2
    results = [evaluate_case(img, gt, build_twin) for img, gt in cases]
    summary = summarize(results)

    for r in results:
        flag = "ERR " if r["error"] else "    "
        print(f"{flag}{r['image']:<28} comp {r['component'].hits}/{r['component'].total}+{r['extra_components']}x  "
              f"wire {r['wire'].hits}/{r['wire'].total}  nets {'ok' if r['nets_equal'] else 'X '}  "
              f"diag {r['diagnosis_equal']}  {r['ms']:.0f} ms" + (f"  {r['error']}" if r["error"] else ""))
    print(f"\nn={summary['n']}  component {M.fmt(summary['component_acc'])}  wire {M.fmt(summary['wire_acc'])}  "
          f"net {M.fmt(summary['net_acc'])}  diagnosis {M.fmt(summary['diagnosis_acc']) or 'n/a'}  "
          f"median {M.fmt(summary['median_ms'], 0)} ms  p90 {M.fmt(summary['p90_ms'], 0)} ms")

    LAST_RUN_JSON.write_text(json.dumps({"note": args.note, "summary": summary, "results": [
        {**r, "component": r["component"].__dict__, "wire": r["wire"].__dict__} for r in results]}, indent=2))
    if not args.dry_run:
        append_history(summary, args.note, path=HISTORY_CSV)
        print(f"appended row to {HISTORY_CSV}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
