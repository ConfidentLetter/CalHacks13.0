import csv
import json
from pathlib import Path

from eval import plot_history, prelabel, run_eval
from eval import truth as T


def _label(testset, name, planted_line=1, corrected=r"f'(x)=2x\sin x+x^{2}\cos x"):
    prelabel.prelabel_page(name, mock=True, testset_dir=testset)
    truth = T.load_truth(name, testset)
    truth["lines"][planted_line].update(planted_error=True, corrected_latex=corrected, planted_note="product rule")
    truth["reviewed"] = True
    T.save_truth(name, truth, testset)


def test_run_eval_mock_end_to_end(testset, tmp_path):
    _label(testset, "1")
    _label(testset, "2")
    hist = tmp_path / "history.csv"
    runs = tmp_path / "runs"
    agg = run_eval.run(["1", "2"], "wiring", mock=True, testset_dir=testset, runs_dir=runs, history_path=hist)
    assert agg["pages"] == 2 and agg["planted_total"] == 2 and agg["planted_preservation"] == 1.0
    assert agg["exact_match"] == 1.0 and agg["line_recall"] == 1.0 and agg["crossed_out_acc"] == 1.0
    assert agg["autocorrections"] == [] and agg["page_ok_rate"] == 1.0
    rows = list(csv.DictReader(hist.open()))
    assert len(rows) == 1 and rows[0]["note"] == "wiring" and rows[0]["planted_preservation"] == "1.0"
    run_dir = next(runs.iterdir())
    assert (run_dir / "report.json").exists() and (run_dir / "1.twin.json").exists()
    report = run_eval.format_report(agg)
    assert "PLANTED-ERROR PRESERVATION  100.0%" in report
    # re-score cached predictions, no model
    agg2 = run_eval.run(["1", "2"], "rescore", mock=False, reuse=run_dir, testset_dir=testset, runs_dir=runs, history_path=hist)
    assert agg2["exact_match"] == 1.0 and len(list(csv.DictReader(hist.open()))) == 2


def test_run_eval_detects_autocorrection(testset, tmp_path):
    _label(testset, "1")
    truth = T.load_truth("1", testset)
    # pretend the student wrote the WRONG thing and the model "fixed" it: truth = mistake, prediction (mock) = correct
    truth["lines"][1]["latex"] = r"f'(x)=2x\cdot\cos x + 1"
    truth["lines"][1]["corrected_latex"] = r"f'(x)=2x\cos x"
    T.save_truth("1", truth, testset)
    agg = run_eval.run(["1"], "autocorrect check", mock=True, testset_dir=testset, runs_dir=tmp_path / "runs", history_path=tmp_path / "h.csv")
    assert agg["planted_preservation"] == 0.0 and len(agg["autocorrections"]) == 1
    assert "AUTOCORRECTED" in run_eval.format_report(agg)


def test_cli_and_plot(testset, tmp_path, monkeypatch, capsys):
    _label(testset, "1")
    hist = tmp_path / "history.csv"
    monkeypatch.setattr(run_eval, "HISTORY_PATH", hist)
    monkeypatch.setattr(run_eval, "RUNS_DIR", tmp_path / "runs")
    assert run_eval.main(["--mock", "--note", "cli", "--testset", str(testset)]) == 0
    assert run_eval.main(["--mock", "--note", "cli 2", "--testset", str(testset)]) == 0
    assert "planted 1/1" in capsys.readouterr().out
    out = tmp_path / "journey.png"
    assert plot_history.main(["--history", str(hist), "--out", str(out)]) == 0
    assert out.exists() and out.stat().st_size > 5000
    assert plot_history.main(["--history", str(tmp_path / "none.csv"), "--out", str(out)]) == 1


def test_cli_without_labels(tmp_path):
    assert run_eval.main(["--mock", "--note", "x", "--testset", str(tmp_path)]) == 1
