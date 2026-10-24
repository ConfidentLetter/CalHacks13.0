"""Calibration fallbacks: manual corners are forwarded, last good H is reused, identity is last."""
import numpy as np

import perception_detect.geometry_bridge as gb


def test_calibrate_falls_back_to_last_good_then_identity(tmp_path, monkeypatch):
    import cv2
    frame = tmp_path / "blank.jpg"
    cv2.imwrite(str(frame), np.full((200, 300, 3), 120, np.uint8))
    good = [[1.0, 0.0, 5.0], [0.0, 1.0, 7.0], [0.0, 0.0, 1.0]]
    calls = []

    class Geo:
        def calibrate(self, path, corners=None):
            calls.append(corners)
            if len(calls) == 1:
                return good
            raise RuntimeError("markers hidden")
    monkeypatch.setattr(gb, "_geometry", lambda: Geo())
    first = gb.calibrate(str(frame))
    assert first.source == "markers_or_corners" and first.calibrated and first.error is None
    second = gb.calibrate(str(frame))
    assert second.source == "last_good" and second.calibrated and second.homography == good
    assert "markers hidden" in second.error
    gb._last_good_h = None
    third = gb.calibrate(str(frame))
    assert third.source == "identity" and not third.calibrated and third.homography == gb.IDENTITY


def test_manual_corners_are_forwarded(monkeypatch):
    seen = {}

    class Geo:
        def calibrate(self, path, corners=None):
            seen["corners"] = corners
            return gb.IDENTITY
    monkeypatch.setattr(gb, "_geometry", lambda: Geo())
    gb.set_manual_corners([(1, 2), (3, 4), (5, 6), (7, 8)])
    gb.calibrate("x.jpg")
    assert seen["corners"] == [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0), (7.0, 8.0)]
    gb.set_manual_corners(None)
    gb.calibrate("x.jpg")
    assert seen["corners"] is None
