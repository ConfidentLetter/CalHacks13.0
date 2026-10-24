"""Step 5: build_page_twin assembles a valid twin with stable ids and change events."""
from pathlib import Path

import pytest

import transcribe.twin as twin_mod
from transcribe.schema import twin_errors


def _line(order, latex, status="active", y=None, conf=0.9, crop_hash="h"):
    y = 300 + 140 * order if y is None else y
    return {"id": "", "region_id": "R1", "order": order, "bbox": [130.0, float(y), 900.0, 100.0], "status": status,
            "kind": "math", "latex": latex, "text": latex, "confidence": conf, "uncertain_spans": [], "parse_ok": True,
            "crop_hash": crop_hash + str(order)}


@pytest.fixture
def fake_pipeline(monkeypatch):
    state = {"lines": [], "quality": {"ok": True, "issues": [], "blur_score": 200.0, "glare_fraction": 0.0}}
    monkeypatch.setattr(twin_mod, "_detect", lambda p: {"dewarped_path": p, "width": 1700, "height": 2200,
                                                        "homography": twin_mod.IDENTITY, "quality": dict(state["quality"])})
    monkeypatch.setattr(twin_mod, "_segment", lambda p: {"regions": [{"id": "R1", "type": "work", "bbox": [120, 280, 1460, 1500]}],
                                                         "lines": []})
    monkeypatch.setattr(twin_mod, "transcribe_page", lambda d, layout, prev=None: [dict(l) for l in state["lines"]])
    return state


def test_first_twin_all_added_and_valid(fake_pipeline):
    fake_pipeline["lines"] = [_line(0, "f(x)=x^{2}\\sin x"), _line(1, "f'(x)=2x\\cdot\\cos x")]
    twin = twin_mod.build_page_twin("runtime/snapshots/upload_1.jpg")
    assert twin_errors(twin) == []
    assert [l["id"] for l in twin["lines"]] == ["L0", "L1"]
    assert twin["changes"] == {"added": ["L0", "L1"], "edited": [], "removed": [], "crossed_out": []}
    assert twin["source"] == "upload" and twin["page_id"].startswith("page_")
    assert all(l["first_seen"] == l["last_changed"] == twin["captured_at"] for l in twin["lines"])
    assert twin["lines"][1]["latex"] == "f'(x)=2x\\cdot\\cos x"  # verbatim mistake preserved through assembly


def test_second_snapshot_keeps_ids_and_reports_changes(fake_pipeline):
    fake_pipeline["lines"] = [_line(0, "f(x)=x^{2}\\sin x"), _line(1, "f'(x)=2x\\cdot\\cos x"), _line(2, "=2\\cos x")]
    first = twin_mod.build_page_twin("a.jpg")
    fake_pipeline["lines"] = [
        _line(0, "f(x)=x^{2}\\sin x"),                       # unchanged
        _line(1, "f'(x)=2x\\cdot\\cos x+1"),                 # edited
        _line(2, "=2\\cos x", status="crossed_out"),          # newly crossed out
        _line(3, "f'(0)=0"),                                  # added
    ]
    second = twin_mod.build_page_twin("b.jpg", first)
    assert twin_errors(second) == []
    assert second["page_id"] == first["page_id"]
    ids = {l["order"]: l["id"] for l in second["lines"]}
    assert ids == {0: "L0", 1: "L1", 2: "L2", 3: "L3"}
    assert second["changes"] == {"added": ["L3"], "edited": ["L1"], "removed": [], "crossed_out": ["L2"]}
    by = {l["id"]: l for l in second["lines"]}
    assert by["L0"]["first_seen"] == by["L0"]["last_changed"] == first["captured_at"]
    assert by["L1"]["last_changed"] == second["captured_at"] and by["L1"]["first_seen"] == first["captured_at"]


def test_removed_lines_and_new_page(fake_pipeline):
    fake_pipeline["lines"] = [_line(0, "a=1"), _line(1, "b=2"), _line(2, "c=3"), _line(3, "d=4")]
    first = twin_mod.build_page_twin("a.jpg")
    fake_pipeline["lines"] = [_line(0, "a=1"), _line(1, "b=2"), _line(2, "c=3")]
    second = twin_mod.build_page_twin("b.jpg", first)
    assert second["page_id"] == first["page_id"] and second["changes"]["removed"] == ["L3"]
    fake_pipeline["lines"] = [_line(0, "x=9", y=900), _line(1, "y=8", y=1300)]
    third = twin_mod.build_page_twin("c.jpg", first)
    assert third["page_id"] != first["page_id"]
    assert third["changes"]["added"] == ["L0", "L1"] and third["changes"]["removed"] == []  # fresh ids on a new page


def test_shifted_line_matches_by_order_and_text(fake_pipeline):
    fake_pipeline["lines"] = [_line(0, "f(x)=x^{2}"), _line(1, "f'(x)=2x")]
    first = twin_mod.build_page_twin("a.jpg")
    fake_pipeline["lines"] = [_line(0, "f(x)=x^{2}", y=620), _line(1, "f'(x)=2x", y=760)]  # page slid down a lot
    second = twin_mod.build_page_twin("b.jpg", first)
    assert [l["id"] for l in second["lines"]] == ["L0", "L1"] and second["changes"]["added"] == []


def test_bad_quality_caps_confidence_and_keeps_good_readings(fake_pipeline):
    fake_pipeline["lines"] = [_line(0, "f(x)=x^{2}\\sin x", conf=0.95), _line(1, "f'(x)=2x\\cdot\\cos x", conf=0.9)]
    first = twin_mod.build_page_twin("a.jpg")
    fake_pipeline["quality"] = {"ok": False, "issues": ["hand_in_frame"], "blur_score": 10.0, "glare_fraction": 0.0}
    fake_pipeline["lines"] = [_line(0, "f(x)=x^{2}\\sin", conf=0.3)]  # line 1 hidden, line 0 misread under the hand
    second = twin_mod.build_page_twin("b.jpg", first)
    assert twin_errors(second) == [] and second["quality"]["ok"] is False
    by = {l["id"]: l for l in second["lines"]}
    assert by["L0"]["latex"] == "f(x)=x^{2}\\sin x" and by["L0"]["confidence"] == 0.95
    assert "L1" in by and by["L1"]["latex"] == "f'(x)=2x\\cdot\\cos x"
    assert second["changes"] == {"added": [], "edited": [], "removed": [], "crossed_out": []}


def test_missing_t1_t2_modules_still_produce_a_valid_twin(monkeypatch, tmp_path):
    import cv2
    import numpy as np

    img_path = tmp_path / "upload_blank.png"
    cv2.imwrite(str(img_path), np.full((400, 600, 3), 250, np.uint8))
    monkeypatch.setattr(twin_mod, "_segment", lambda p: {"regions": [], "lines": []})
    monkeypatch.setattr(twin_mod, "transcribe_page", lambda d, layout, prev=None: [])
    twin = twin_mod.build_page_twin(str(img_path))
    assert twin_errors(twin) == [] and twin["lines"] == []
    # T1 may dewarp to a fixed frame or keep a flat upload's size: trust whatever file it hands back.
    dewarped = cv2.imread(str(twin_mod.resolve(twin["image"]["dewarped_path"])))
    assert dewarped is not None and (twin["image"]["width"], twin["image"]["height"]) == (dewarped.shape[1], dewarped.shape[0])
    assert twin["latency_ms"]["total"] >= 0


def test_mock_twin_backup_is_valid():
    assert twin_errors(twin_mod.mock_twin("x.jpg")) == []


def test_new_page_under_bad_quality_does_not_carry_old_lines(fake_pipeline):
    fake_pipeline["lines"] = [_line(0, "a=1"), _line(1, "b=2"), _line(2, "c=3")]
    first = twin_mod.build_page_twin("a.jpg")
    fake_pipeline["quality"] = {"ok": False, "issues": ["blur"], "blur_score": 1.0, "glare_fraction": 0.0}
    fake_pipeline["lines"] = [_line(0, "q=7", y=1500), _line(1, "r=8", y=1700)]
    second = twin_mod.build_page_twin("b.jpg", first)
    assert second["page_id"] != first["page_id"]
    assert [l["latex"] for l in second["lines"]] == ["q=7", "r=8"]
    assert second["changes"]["added"] == ["L0", "L1"] and second["changes"]["edited"] == []


def test_twin_latency_and_repo_relative_paths(fake_pipeline):
    fake_pipeline["lines"] = [_line(0, "a=1")]
    twin = twin_mod.build_page_twin(str(twin_mod.REPO_ROOT / "runtime" / "snapshots" / "upload_x.jpg"))
    assert twin["latency_ms"]["snapshot_to_twin"] == twin["latency_ms"]["total"] >= 0
    assert twin["image"]["original_path"] == "runtime/snapshots/upload_x.jpg"
    assert twin["image"]["dewarped_path"] == "runtime/snapshots/upload_x.jpg"


@pytest.mark.parametrize("broken", ["_detect", "_segment", "transcribe_page", "match_to_previous"])
def test_build_page_twin_never_raises(fake_pipeline, monkeypatch, broken):
    def boom(*a, **k):
        raise RuntimeError("boom in " + broken)

    monkeypatch.setattr(twin_mod, broken, boom)
    twin = twin_mod.build_page_twin("runtime/uploads/still.jpg", {"page_id": "page_keep", "lines": []})
    assert twin_errors(twin) == []
    assert twin["quality"]["ok"] is False and twin["lines"] == [] and "boom" in twin["_error"]
    assert twin["page_id"] == "page_keep" and twin["latency_ms"]["snapshot_to_twin"] >= 0


def test_absolute_and_relative_paths_both_work(fake_pipeline, tmp_path, monkeypatch):
    import cv2
    import numpy as np

    seen = []
    monkeypatch.setattr(twin_mod, "_detect", lambda p: (seen.append(p), {"dewarped_path": p, "width": 0, "height": 0,
                                                                        "homography": twin_mod.IDENTITY,
                                                                        "quality": {"ok": True, "issues": []}})[1])
    uploads = twin_mod.REPO_ROOT / "runtime" / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    img = uploads / "t3_test_still.jpg"
    cv2.imwrite(str(img), np.full((300, 400, 3), 250, np.uint8))
    try:
        for given in (str(img), "runtime/uploads/t3_test_still.jpg"):
            twin = twin_mod.build_page_twin(given)
            assert twin_errors(twin) == [] and twin["image"]["original_path"] == "runtime/uploads/t3_test_still.jpg"
            assert (twin["image"]["width"], twin["image"]["height"]) == (400, 300)
        assert all(Path(p).is_absolute() for p in seen), "T1 always receives an absolute path"
    finally:
        img.unlink(missing_ok=True)
