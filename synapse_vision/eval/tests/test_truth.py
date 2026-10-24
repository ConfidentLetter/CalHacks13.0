import json

from eval import truth as T


def test_page_names_sorted_numerically(testset):
    (testset / "10.jpg").write_bytes((testset / "1.jpg").read_bytes())
    (testset / "glare.png").write_bytes((testset / "1.jpg").read_bytes())
    assert T.page_names(testset) == ["1", "2", "10", "glare"]


def test_truth_from_mock_twin_validates(mock_truth):
    assert T.validate_truth(mock_truth) == []
    assert len(mock_truth["lines"]) == 4
    assert all(l["planted_error"] is False for l in mock_truth["lines"])
    assert mock_truth["lines"][2]["status"] == "crossed_out"
    assert mock_truth["lines"][1]["latex"] == "f'(x)=2x\\cdot\\cos x"  # verbatim, mistake kept


def test_save_and_load_roundtrip(testset, mock_truth):
    p = T.save_truth("1", mock_truth, testset)
    assert p.name == "1.truth.json"
    assert T.load_truth("1", testset) == json.loads(p.read_text())
    assert T.load_truth("2", testset) is None


def test_validate_rejects_bad_shapes(mock_truth):
    bad = json.loads(json.dumps(mock_truth))
    bad["lines"][0]["bbox"] = [1, 2]
    bad["lines"][1]["status"] = "weird"
    bad["lines"][2]["planted_error"] = True
    errs = T.validate_truth(bad)
    assert any("bbox" in e for e in errs) and any("status" in e for e in errs) and any("corrected_latex" in e for e in errs)


def test_unsafe_names_rejected(testset):
    import pytest
    with pytest.raises(ValueError):
        T.truth_path("../x", testset)
