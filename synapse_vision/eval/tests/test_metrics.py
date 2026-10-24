import pytest

from eval import metrics as M


def test_iou_and_matching():
    assert M.iou([0, 0, 10, 10], [0, 0, 10, 10]) == 1.0
    assert M.iou([0, 0, 10, 10], [20, 20, 5, 5]) == 0.0
    pred = [{"bbox": [0, 0, 100, 20], "order": 0}, {"bbox": [0, 50, 100, 20], "order": 1}, {"bbox": [500, 500, 10, 10], "order": 2}]
    truth = [{"bbox": [2, 1, 100, 20], "order": 0}, {"bbox": [0, 52, 100, 20], "order": 1}, {"bbox": [0, 100, 100, 20], "order": 2}]
    m = M.match_lines(pred, truth)
    assert m["pairs"] == [(0, 0), (1, 1)] and m["unmatched_pred"] == [2] and m["unmatched_truth"] == [2]


def test_merged_and_order():
    truth = [{"bbox": [0, 0, 100, 20], "order": 0}, {"bbox": [0, 30, 100, 20], "order": 1}]
    assert M.merged_line_count([{"bbox": [0, 0, 100, 50]}], truth) == 1
    assert M.merged_line_count([{"bbox": [0, 0, 100, 20]}], truth) == 0
    pred = [{"bbox": [0, 0, 100, 20], "order": 1}, {"bbox": [0, 30, 100, 20], "order": 0}]
    assert M.reading_order_accuracy([(0, 0), (1, 1)], pred, truth) == 0.0
    assert M.reading_order_accuracy([(0, 0)], pred, truth) is None


def test_cer():
    assert M.cer("abc", "abc") == 0.0
    assert M.cer("abd", "abc") == pytest.approx(1 / 3)
    assert M.cer("", "") == 0.0 and M.cer("x", "") == 1.0


def test_equivalent_sympy_and_exact():
    assert M.equivalent(r"f'(x)=2x\cdot\cos x", r"f'(x)=2x \cos x")[0]
    ok, how = M.equivalent(r"f'(x)=2x\cdot\cos x", r"f'(x)=2x\sin x+x^{2}\cos x")
    assert not ok and how == "sympy"
    assert M.equivalent(r"2x\cos x", r"2x=\cos x") == (False, "exact")
    assert M.equivalent(r"\text{garbage}", r"\text{garbage}") == (True, "exact")


def _lines(*specs):
    out = []
    for i, (latex, status, conf) in enumerate(specs):
        out.append({"id": f"L{i}", "order": i, "bbox": [0, i * 100, 500, 50], "latex": latex, "status": status, "confidence": conf})
    return out


def test_score_page_planted_preserved_and_autocorrected():
    truth = _lines((r"f(x)=x^{2}\sin x", "active", 1), (r"f'(x)=2x\cos x", "active", 1), (r"=2\cos x", "crossed_out", 1))
    truth[1].update(planted_error=True, corrected_latex=r"f'(x)=2x\sin x+x^{2}\cos x", planted_note="product rule")
    good = _lines((r"f(x)=x^{2}\sin x", "active", 0.95), (r"f'(x)=2x\cdot\cos x", "active", 0.9), (r"=2\cos x", "crossed_out", 0.5))
    s = M.score_page(good, truth)
    assert s["tp"] == 3 and s["planted_total"] == 1 and s["planted_preserved"] == 1 and s["autocorrections"] == []
    # 2x\cdot\cos x vs 2x\cos x: not an exact normalized match (T3 keeps \cdot as *), but SymPy-equivalent -> preserved
    assert s["exact"] == 2 and s["crossed_correct"] == 3 and s["calib"] == {"hi": [1, 2], "mid": [0, 0], "lo": [1, 1]}
    bad = _lines((r"f(x)=x^{2}\sin x", "active", 0.95), (r"f'(x)=2x\sin x+x^{2}\cos x", "active", 0.9), (r"=2\cos x", "active", 0.5))
    s = M.score_page(bad, truth)
    assert s["planted_preserved"] == 0 and len(s["autocorrections"]) == 1 and s["autocorrections"][0]["note"] == "product rule"
    assert s["crossed_correct"] == 2 and s["exact"] == 2


def test_score_page_undetected_planted_line_counts_as_missed():
    truth = _lines((r"a", "active", 1), (r"b", "active", 1))
    truth[1].update(planted_error=True, corrected_latex="c")
    s = M.score_page(_lines(("a", "active", 0.9)), truth)
    assert s["planted_total"] == 1 and s["planted_missed"][0]["reason"] == "line not detected"
    agg = M.aggregate([s])
    assert agg["planted_preservation"] == 0.0 and agg["line_recall"] == 0.5 and agg["exact_match"] == 1.0
