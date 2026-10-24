import numpy as np
import pytest

from capture import source
from capture.compat import RUNTIME_DIR


def test_upload_copies_into_runtime_snapshots(synth_photo):
    out = source.get_snapshot(f"upload:{synth_photo['path']}")
    assert out.startswith("runtime/snapshots/"), "paths are repo-relative so T4's viewer can serve them"
    import cv2

    img = cv2.imread(str(RUNTIME_DIR.parent / out))
    assert img is not None and img.shape[:2] == synth_photo["sample"].image.shape[:2]


def test_upload_env_default(synth_photo, monkeypatch):
    monkeypatch.setenv("SV_SOURCE", f"upload:{synth_photo['path']}")
    assert source.get_snapshot().endswith(".jpg")


def test_upload_missing_file_raises(tmp_path):
    with pytest.raises(source.SourceError):
        source.get_snapshot(f"upload:{tmp_path / 'missing.jpg'}")


def test_unknown_source_raises():
    with pytest.raises(source.SourceError):
        source.get_snapshot("telepathy")


def test_wait_for_stable_with_upload_source_returns_immediately(synth_photo, monkeypatch):
    monkeypatch.setenv("SV_SOURCE", f"upload:{synth_photo['path']}")
    assert source.wait_for_stable(timeout_s=0.1) is not None


def test_frame_diff_zero_for_identical_and_positive_for_different():
    a = np.full((480, 640, 3), 120, np.uint8)
    b = a.copy()
    b[100:300, 100:400] = 0
    assert source.frame_diff(a, a) == 0.0
    assert source.frame_diff(a, b) > 0.02


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _frames():
    still = np.full((480, 640, 3), 120, np.uint8)
    moving = still.copy()
    moving[0:240, :] = 0
    return still, moving


def test_stability_monitor_fires_once_after_change_then_quiet():
    clock = FakeClock()
    m = source.StabilityMonitor(change_threshold=0.02, stable_seconds=1.0, clock=clock)
    still, moving = _frames()
    fired = []
    for frame in [still, still, moving, moving, still, still, still, still, still, still, still]:
        clock.t += 0.2
        fired.append(m.update(frame))
    assert fired.count(True) == 1
    assert fired.index(True) >= 4 + 5, "must wait ~1 s of quiet after the last change"


def test_stability_monitor_does_not_fire_while_scene_still_changing():
    clock = FakeClock()
    m = source.StabilityMonitor(change_threshold=0.02, stable_seconds=1.0, clock=clock)
    still, moving = _frames()
    seq = [still, moving, still, moving, still, moving, still, moving]
    for frame in seq:
        clock.t += 0.2
        assert m.update(frame) is False


def test_stability_monitor_never_fires_on_an_unchanging_scene():
    clock = FakeClock()
    m = source.StabilityMonitor(change_threshold=0.02, stable_seconds=1.0, clock=clock)
    still, _ = _frames()
    for _ in range(30):
        clock.t += 0.2
        assert m.update(still) is False
