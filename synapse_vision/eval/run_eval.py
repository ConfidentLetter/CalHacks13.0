"""Evaluate the pipeline on the labelled test set and append a row to eval/history.csv.

    python -m eval.run_eval --note "H+8 first real run"
    python -m eval.run_eval --mock --note "wiring check"      # mock twin instead of the model
    python -m eval.run_eval --reuse eval/runs/<ts> --note ... # re-score cached predictions

Reads eval/testset/<n>.truth.json (reviewed or not; unreviewed are reported but flagged).
Writes eval/runs/<ts>/<n>.twin.json + report.json, prints the report, appends history.csv.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from app import telemetry
from app.config import get as cfg
from eval import metrics as M
from eval import truth as T
from eval.prelabel import predict

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "eval" / "history.csv"
RUNS_DIR = ROOT / "eval" / "runs"

HISTORY_COLUMNS = [
    "ts", "note", "pages", "reviewed_pages", "lines_truth", "page_ok_rate", "line_precision", "line_recall", "merged_lines",
    "order_acc", "exact_match", "cer", "crossed_out_acc", "planted_total", "planted_preserved", "planted_preservation",
    "autocorrections", "verbatim_guard_risky", "calib_hi_acc", "calib_mid_acc", "calib_lo_acc", "latency_p50_ms",
    "latency_p90_ms", "incremental_p50_ms", "model",
]
VERBATIM_GUARD_PATH = ROOT / "runtime" / "debug" / "verbatim_guard.jsonl"


def _scaled_pred_lines(twin: dict, truth: dict) -> list[dict]:
    """Prediction lines with boxes rescaled into the truth image's pixel frame (if sizes differ)."""
    pw, ph = twin.get("image", {}).get("width") or 0, twin.get("image", {}).get("height") or 0
    tw, th = truth.get("width") or 0, truth.get("height") or 0
    sx = tw / pw if pw and tw else 1.0
    sy = th / ph if ph and th else 1.0
    out = []
    for l in twin.get("lines", []):
        x, y, w, h = l["bbox"]
        out.append({**l, "bbox": [x * sx, y * sy, w * sx, h * sy]})
    return out


def _page_ok(twin: dict) -> bool:
    return bool(twin.get("quality", {}).get("ok"))


def _corner_error(twin: dict, truth: dict) -> float | None:
    """Mean corner distance / page diagonal when both sides provide original-image corners."""
    pc, tc = twin.get("image", {}).get("corners_original"), truth.get("page_corners")
    if not (pc and tc and len(pc) == 4 and len(tc) == 4):
        return None
    diag = (truth["width"] ** 2 + truth["height"] ** 2) ** 0.5
    d = sum(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(pc, tc)) / 4
    return d / diag if diag else None


def evaluate_page(name: str, twin: dict, truth: dict) -> dict:
    pred = _scaled_pred_lines(twin, truth)
    score = M.score_page(pred, truth["lines"])
    score.update({
        "name": name, "reviewed": bool(truth.get("reviewed")), "page_ok": _page_ok(twin),
        "corner_error": _corner_error(twin, truth),
        "latency_ms": (twin.get("latency_ms") or {}).get("snapshot_to_twin") or (twin.get("latency_ms") or {}).get("total"),
        "stage_latency_ms": {k: v for k, v in (twin.get("latency_ms") or {}).items() if k not in ("snapshot_to_twin", "total")},
        "fallback": twin.get("_fallback"),
    })
    return score


def verbatim_guard_stats(path: Path = VERBATIM_GUARD_PATH, since: datetime | None = None) -> dict:
    """T3's runtime/debug/verbatim_guard.jsonl: every disagreement where one reading was mathematically 'nicer'.

    `chosen_is_nicer: true` = the system picked the nicer reading = the risky cases (possible autocorrection).
    """
    total = risky = 0
    examples: list[dict] = []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"total": 0, "risky": 0, "examples": []}
    for raw in lines:
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if since and rec.get("ts") and str(rec["ts"]) < since.isoformat():
            continue
        total += 1
        if rec.get("chosen_is_nicer"):
            risky += 1
            if len(examples) < 10:
                examples.append({k: rec.get(k) for k in ("line_id", "nicer", "reread_choice", "final", "snapshot_id")})
    return {"total": total, "risky": risky, "examples": examples}


def incremental_latencies() -> list[float]:
    """New-line incremental times, from telemetry stages that mention 'incremental' or 'new_line'."""
    return [r["ms"] for r in telemetry.read() if any(k in str(r.get("stage", "")) for k in ("incremental", "new_line"))]


def run(names: list[str], note: str, mock: bool = False, reuse: Path | None = None, testset_dir: Path | None = None,
        write_history: bool = True, runs_dir: Path = RUNS_DIR, history_path: Path = HISTORY_PATH) -> dict:
    ts = datetime.now(timezone.utc).astimezone()
    run_dir = reuse or (runs_dir / ts.strftime("%Y%m%dT%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=True)
    pages: list[dict] = []
    for name in names:
        truth = T.load_truth(name, testset_dir)
        image = T.image_path(name, testset_dir)
        if truth is None or image is None:
            print(f"{name}: skipped (no truth or no photo)", file=sys.stderr)
            continue
        cached = run_dir / f"{name}.twin.json"
        if reuse and cached.exists():
            twin = json.loads(cached.read_text(encoding="utf-8"))
        else:
            try:
                twin = predict(image, mock=mock)
            except Exception as exc:  # noqa: BLE001 - one bad page must not kill the run
                print(f"{name}: pipeline failed: {type(exc).__name__}: {exc}", file=sys.stderr)
                twin = {"lines": [], "quality": {"ok": False, "issues": []}, "image": {}, "_fallback": f"error: {exc}"}
            cached.write_text(json.dumps(twin, ensure_ascii=False, indent=1), encoding="utf-8")
        pages.append(evaluate_page(name, twin, truth))

    agg = M.aggregate(pages)
    lat = [p["latency_ms"] for p in pages if p.get("latency_ms") is not None]
    inc = incremental_latencies()
    guard = verbatim_guard_stats(since=ts if not reuse else None)
    agg.update({
        "verbatim_guard_total": guard["total"], "verbatim_guard_risky": guard["risky"], "verbatim_guard_examples": guard["examples"],
        "ts": ts.isoformat(timespec="seconds"), "note": note, "run_dir": T.rel(run_dir),
        "reviewed_pages": sum(1 for p in pages if p["reviewed"]),
        "page_ok_rate": sum(1 for p in pages if p["page_ok"]) / len(pages) if pages else None,
        "corner_errors": [p["corner_error"] for p in pages if p["corner_error"] is not None],
        "latency_p50_ms": M.p50(lat), "latency_p90_ms": M.percentile(lat, 0.9), "incremental_p50_ms": M.p50(inc),
        "model": __import__("os").environ.get("SV_MODEL", "claude-sonnet-5-5") if not mock else "mock",
        "budget_ms": cfg("budget_ms", {}),
        "per_page": pages,
    })
    (run_dir / "report.json").write_text(json.dumps(agg, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if write_history:
        append_history(agg, history_path)
    return agg


def append_history(agg: dict, history_path: Path = HISTORY_PATH) -> None:
    row = {k: agg.get(k) for k in HISTORY_COLUMNS}
    row["autocorrections"] = len(agg.get("autocorrections", []))
    for k, v in row.items():
        if isinstance(v, float):
            row[k] = round(v, 4)
    existing: list[dict] = []
    if history_path.exists():
        with history_path.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            if reader.fieldnames and list(reader.fieldnames) != HISTORY_COLUMNS:
                existing = list(reader)  # columns changed: rewrite old rows under the new header (blanks for new columns)
    mode = "w" if existing else "a"
    write_header = mode == "w" or not history_path.exists()
    with history_path.open(mode, newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=HISTORY_COLUMNS, extrasaction="ignore")
        if write_header:
            w.writeheader()
        for old in existing:
            w.writerow({k: old.get(k, "") for k in HISTORY_COLUMNS})
        w.writerow(row)


def _pct(v) -> str:
    return "  n/a " if v is None else f"{100 * v:5.1f}%"


def format_report(agg: dict) -> str:
    lines = [
        f"== Synapse Vision eval — {agg['ts']} — {agg['note']}",
        f"pages {agg['pages']} (reviewed {agg['reviewed_pages']}), truth lines {agg['lines_truth']}, model {agg['model']}",
        f"PLANTED-ERROR PRESERVATION  {_pct(agg['planted_preservation'])}  ({agg['planted_preserved']}/{agg['planted_total']})",
    ]
    for a in agg["autocorrections"]:
        lines.append(f"  AUTOCORRECTED  {a['truth_id']}  wrote {a['truth']!r}  read {a['pred']!r}  (= corrected {a['corrected']!r})  {a['note']}")
    for a in agg["planted_missed"]:
        lines.append(f"  missed         {a['truth_id']}  wrote {a['truth']!r}  read {a['pred']!r}  {a.get('reason', '')} {a['note']}")
    lines.append(f"verbatim guard  {agg['verbatim_guard_risky']} risky (chose the 'nicer' reading) of {agg['verbatim_guard_total']} disagreements this run")
    for g in agg["verbatim_guard_examples"]:
        lines.append(f"  RISKY          {g.get('line_id')}  nicer {g.get('nicer')!r}  final {g.get('final')!r}  ({g.get('reread_choice')})")
    lines += [
        f"page detection ok           {_pct(agg['page_ok_rate'])}" + (f"  corner err mean {sum(agg['corner_errors']) / len(agg['corner_errors']):.3%}" if agg["corner_errors"] else "  (no corner truth)"),
        f"line detection  P {_pct(agg['line_precision'])}  R {_pct(agg['line_recall'])}  merged {agg['merged_lines']}  order {_pct(agg['order_acc'])}",
        f"transcription   exact {_pct(agg['exact_match'])}  CER {agg['cer']:.3f}  crossed-out {_pct(agg['crossed_out_acc'])}" if agg["cer"] is not None else "transcription   n/a (no matched lines)",
        f"calibration     ≥0.8 {_pct(agg['calib_hi_acc'])} (n={agg['calib_counts']['hi']})  0.6–0.8 {_pct(agg['calib_mid_acc'])} (n={agg['calib_counts']['mid']})  <0.6 {_pct(agg['calib_lo_acc'])} (n={agg['calib_counts']['lo']})",
        f"latency         p50 {agg['latency_p50_ms']} ms  p90 {agg['latency_p90_ms']} ms  (budget {agg['budget_ms'].get('snapshot_to_twin_first')})  incremental p50 {agg['incremental_p50_ms']} ms (budget {agg['budget_ms'].get('new_line_incremental')})",
    ]
    for p in agg["per_page"]:
        flag = "" if p["reviewed"] else " [unreviewed]"
        fb = f" [{p['fallback']}]" if p.get("fallback") else ""
        lines.append(f"  {p['name']:>16}: {p['tp']}/{p['n_truth']} lines, exact {p['exact']}/{p['tp']}, planted {p['planted_preserved']}/{p['planted_total']}{flag}{fb}")
        for mm in p["mismatches"][:6]:
            lines.append(f"{'':>20}✗ {mm['truth_id']} wrote {mm['truth']!r} read {mm['pred']!r} (conf {mm['confidence']:.2f})")
    lines.append(f"report: {agg['run_dir']}/report.json")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--note", required=True, help="what changed since the last row (goes on the chart)")
    p.add_argument("--mock", action="store_true")
    p.add_argument("--reuse", default=None, help="eval/runs/<ts> dir with cached *.twin.json to re-score")
    p.add_argument("--only", nargs="*", default=None)
    p.add_argument("--testset", default=None)
    p.add_argument("--no-history", action="store_true")
    a = p.parse_args(argv)
    testset = Path(a.testset) if a.testset else None
    names = a.only or [n for n in T.page_names(testset or T.TESTSET_DIR) if T.load_truth(n, testset)]
    if not names:
        print("no labelled pages: run `python -m eval.prelabel` and correct at /label first")
        return 1
    agg = run(names, a.note, mock=a.mock, reuse=Path(a.reuse) if a.reuse else None, testset_dir=testset,
              write_history=not a.no_history, runs_dir=RUNS_DIR, history_path=HISTORY_PATH)
    print(format_report(agg))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
