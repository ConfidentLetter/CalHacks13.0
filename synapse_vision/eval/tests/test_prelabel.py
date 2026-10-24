from eval import prelabel
from eval import truth as T


def test_prelabel_mock_writes_truth(testset):
    out = prelabel.prelabel_page("1", mock=True, testset_dir=testset)
    assert out is not None and out.exists()
    truth = T.load_truth("1", testset)
    assert T.validate_truth(truth) == []
    assert truth["reviewed"] is False and len(truth["lines"]) == 4
    assert truth["image"].endswith("testset/1.jpg")


def test_prelabel_skips_existing_unless_forced_and_never_reviewed(testset):
    assert prelabel.prelabel_page("1", mock=True, testset_dir=testset)
    assert prelabel.prelabel_page("1", mock=True, testset_dir=testset) is None
    assert prelabel.prelabel_page("1", mock=True, force=True, testset_dir=testset)
    truth = T.load_truth("1", testset)
    truth["reviewed"] = True
    T.save_truth("1", truth, testset)
    assert prelabel.prelabel_page("1", mock=True, force=True, testset_dir=testset) is None


def test_prelabel_missing_photo_returns_none(testset):
    assert prelabel.prelabel_page("99", mock=True, testset_dir=testset) is None


def test_main_cli(testset, capsys):
    assert prelabel.main(["--mock", "--testset", str(testset)]) == 0
    out = capsys.readouterr().out
    assert "2/2 pre-labelled" in out


def test_main_cli_empty_testset(tmp_path, capsys):
    assert prelabel.main(["--mock", "--testset", str(tmp_path)]) == 1
