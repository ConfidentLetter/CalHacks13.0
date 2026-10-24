"""End-to-end on a synthetic test set built from the mocks; the stub build_twin returns twin_ok."""
import csv
import json
from pathlib import Path

import run_eval

MOCKS = Path(__file__).resolve().parents[2] / "mocks"


def _make_testset(tmp_path):
    tmp_path.mkdir(parents=True, exist_ok=True)
    for name in ("twin_ok", "twin_sda_swapped", "twin_5v"):
        gt = json.loads((MOCKS / f"{name}.json").read_text())
        gt["expected_findings"] = [] if name == "twin_ok" else ["dummy"]
        (tmp_path / f"{name}.jpg").write_bytes(b"\xff\xd8not-really-a-jpeg")
        (tmp_path / f"{name}.twin.json").write_text(json.dumps(gt))
    return tmp_path


def test_run_eval_appends_history_row(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_MOCK", "1")          # mock twin for every image: exercises the plumbing
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path / "runtime"))
    ts = _make_testset(tmp_path / "testset")
    hist = tmp_path / "history.csv"
    monkeypatch.setattr(run_eval, "HISTORY_CSV", hist)
    monkeypatch.setattr(run_eval, "LAST_RUN_JSON", tmp_path / "last_run.json")
    assert run_eval.main(["--note", "unit test", "--testset", str(ts)]) == 0
    rows = list(csv.DictReader(hist.open()))
    assert len(rows) == 1
    row = rows[0]
    assert row["note"] == "unit test"
    assert row["component_acc"] == "1.000"      # mock twin has the right components for every case
    assert row["net_acc"] == f"{1/3:.3f}"        # only twin_ok's nets match the mock
    assert row["wire_acc"] == f"{(12 + 10 + 11) / 38:.3f}"   # ok, swapped, 5v (7 GT wires)
    assert float(row["median_ms"]) >= 0
    assert (tmp_path / "last_run.json").is_file()


def test_run_eval_no_cases_returns_2(tmp_path):
    assert run_eval.main(["--note", "x", "--testset", str(tmp_path)]) == 2
