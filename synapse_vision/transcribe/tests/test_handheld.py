"""Regression: a hand-held printed worksheet (bottom edge out of frame, face + hall behind it).
T1 reports no_page and T2 finds nothing on the raw frame; the loose page crop must still get it read.
Fixture = Henry's real still 20261025T152938 downscaled to 800x450. Model calls are faked."""
from pathlib import Path

import pytest

import transcribe.rawframe as raw
import transcribe.twin as twin_mod
from transcribe.loosepage import loose_page
from transcribe.schema import twin_errors

FIXTURE = Path(__file__).parent / "fixtures" / "handheld_sheet_800.jpg"
READS = [{"latex": "\\sum F_y=N-mg=0", "text": "ΣFy = N - mg = 0", "kind": "math", "illegible": False, "uncertain": []},
         {"latex": "T-\\mu_k m_1g=2m_1a_2", "text": "T - μk m1 g = 2 m1 a2", "kind": "math", "illegible": False, "uncertain": []}]


def test_loose_page_crops_the_sheet_and_drops_the_face():
    lp = loose_page(str(FIXTURE))
    assert lp is not None
    x, y, w, h = lp["bbox_in_frame"]
    # the sheet spans roughly x 215..690 of 800; the face sits left of x≈215 and must be outside the crop
    assert x >= 180 and x + w <= 720 and w * h >= 0.25 * 800 * 450
    assert max(lp["width"], lp["height"]) == 2200


def test_handheld_still_is_read_with_quality_reported_honestly(monkeypatch):
    calls = []
    monkeypatch.setattr(raw, "page_pass", lambda tiles: calls.append(tiles[0]["path"]) or [dict(r) for r in READS])
    twin = twin_mod.build_page_twin(str(FIXTURE))
    assert twin_errors(twin) == []
    assert len(twin["lines"]) > 0, "a hand-held sheet must not come back empty"
    assert [l["latex"] for l in twin["lines"]] == [r["latex"] for r in READS]  # verbatim, untouched
    assert twin["quality"]["ok"] is False and "no_page" in twin["quality"]["issues"]
    assert all(l["confidence"] <= 0.4 for l in twin["lines"])
    # the model saw the cropped sheet, not the raw frame with the face, and the twin's image is that crop
    assert calls and calls[0].endswith("_loose.png") and twin["image"]["dewarped_path"].endswith("_loose.png")
    W, H = twin["image"]["width"], twin["image"]["height"]
    for l in twin["lines"]:
        x, y, w, h = l["bbox"]
        assert l["bbox_estimated"] is True and 0 <= x and x + w <= W and 0 <= y and y + h <= H


def test_good_pages_never_take_the_handheld_path(monkeypatch):
    monkeypatch.setattr(twin_mod, "loose_page", lambda p: pytest.fail("fallback must not run on a good page"))
    monkeypatch.setattr(twin_mod, "_detect", lambda p: {"dewarped_path": p, "width": 10, "height": 10,
                                                        "homography": twin_mod.IDENTITY, "quality": {"ok": True, "issues": []}})
    monkeypatch.setattr(twin_mod, "_segment", lambda p: {"regions": [], "lines": []})
    assert twin_mod.build_page_twin(str(FIXTURE))["lines"] == []


def test_empty_sheet_read_falls_through_to_the_whole_frame(monkeypatch):
    """If the sheet crop reads nothing (crop landed on the wrong bright thing), the whole frame gets one try."""
    seen = []

    def fake_pass(tiles):
        seen.append(tiles[0]["path"])
        return [] if tiles[0]["path"].endswith("_loose.png") else [dict(READS[0])]

    monkeypatch.setattr(raw, "page_pass", fake_pass)
    twin = twin_mod.build_page_twin(str(FIXTURE))
    assert len(seen) == 2 and seen[0].endswith("_loose.png") and seen[1].endswith("handheld_sheet_800.jpg")
    assert [l["latex"] for l in twin["lines"]] == [READS[0]["latex"]] and twin_errors(twin) == []
