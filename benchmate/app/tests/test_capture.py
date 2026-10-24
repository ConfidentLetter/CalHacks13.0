"""Tests for app.capture (Step 2). No real camera: synthetic sources + fake clock."""
import json
import time

import numpy as np
import pytest

from app import capture
from app.capture import Camera, ChangeDetector, SyntheticSource, to_small_gray


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path))
    return tmp_path


def board(shade=120, w=320, h=180):
    return np.full((h, w, 3), shade, dtype=np.uint8)


def with_hand(shade=120):
    f = board(shade)
    f[40:140, 100:220] = 230  # a bright "hand" blob
    return f


def with_wire_moved(shade=120):
    f = board(shade)
    f[90:94, 20:300] = (0, 200, 200)  # a new thin yellow wire
    return f


# ---------------------------------------------------------------- ChangeDetector state machine
class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t

    def tick(self, dt=0.1):
        self.t += dt
        return self.t


def feed(det, frame, clock, n=1, dt=0.1):
    fired = []
    for _ in range(n):
        fired.append(det.update(to_small_gray(frame), clock.tick(dt)))
    return fired


def test_first_frame_is_reference_and_nothing_fires():
    det, clock = ChangeDetector(), Clock()
    assert feed(det, board(), clock, n=20) == [False] * 20
    assert det.state == det.STABLE


def test_sensor_noise_below_threshold_does_not_fire():
    det, clock = ChangeDetector(threshold=0.02), Clock()
    feed(det, board(), clock)
    rng = np.random.default_rng(0)
    for _ in range(30):
        noisy = np.clip(board().astype(int) + rng.integers(-2, 3, board().shape), 0, 255).astype(np.uint8)
        assert det.update(to_small_gray(noisy), clock.tick()) is False


def test_hand_enters_moves_wire_leaves_fires_exactly_once_after_settle():
    det, clock = ChangeDetector(threshold=0.02, settle_seconds=0.8), Clock()
    feed(det, board(), clock)
    # hand moves around for 1.5 s: changing, never still -> never fires
    fired = []
    for i in range(15):
        f = with_hand()
        f[40:140, 100 + (i % 2) * 40:220 + (i % 2) * 40] = 230  # jitter the hand each frame
        fired.append(det.update(to_small_gray(f), clock.tick()))
    assert not any(fired) and det.state == det.CHANGING
    # hand leaves, wire moved. Frame 1 is the transition (not "still"); stillness is measured
    # from frame 2, so 0.8 s of quiet video is reached on frame 10.
    assert feed(det, with_wire_moved(), clock, n=9) == [False] * 9
    assert feed(det, with_wire_moved(), clock, n=1) == [True]
    assert det.state == det.STABLE
    # stays quiet afterwards
    assert feed(det, with_wire_moved(), clock, n=20) == [False] * 20


def test_hand_passes_through_board_unchanged_fires_once_then_quiet():
    det, clock = ChangeDetector(), Clock()
    feed(det, board(), clock)
    feed(det, with_hand(), clock, n=5)
    fired = feed(det, board(), clock, n=12)
    assert fired.count(True) == 1
    assert feed(det, board(), clock, n=10) == [False] * 10


def test_threshold_is_respected():
    det, clock = ChangeDetector(threshold=0.5), Clock()  # absurdly high
    feed(det, board(), clock)
    assert not any(feed(det, with_hand(), clock, n=5) + feed(det, with_wire_moved(), clock, n=15))


# ---------------------------------------------------------------- Camera thread with a fake source
class ScriptedSource(capture.FrameSource):
    """Returns frames from a list, then repeats the last one. Switchable at runtime."""

    name = "scripted"

    def __init__(self, frame):
        self.frame = frame

    def read(self):
        time.sleep(0.01)
        return self.frame.copy()


def test_camera_writes_latest_jpg_and_get_frame_paths(runtime):
    src = ScriptedSource(board())
    cam = Camera(source_factory=lambda: src).start()
    try:
        path = cam.get_frame()
        assert path.endswith("latest.jpg")
        deadline = time.time() + 2
        while not (runtime / "frames" / "latest.jpg").exists() and time.time() < deadline:
            time.sleep(0.02)
        assert (runtime / "frames" / "latest.jpg").exists()
        assert cam.latest_jpeg()[:2] == b"\xff\xd8"  # JPEG magic
        still1 = cam.get_frame(high_res=True)
        time.sleep(0.002)
        still2 = cam.get_frame(high_res=True)
        assert still1 != still2 and still1.split("/")[-1].startswith("still_")
        assert (runtime / "frames" / still1.split("/")[-1]).stat().st_size > 1000
        assert cam.info["source"] == "scripted"
    finally:
        cam.stop()


def test_camera_frame_changed_end_to_end(runtime):
    src = ScriptedSource(board())
    cam = Camera(source_factory=lambda: src, write_files=False)
    cam.detector.settle_seconds = 0.3  # keep the test fast
    cam.start()
    try:
        time.sleep(0.2)
        assert cam.frame_changed() is False
        src.frame = with_hand()
        time.sleep(0.15)
        src.frame = with_wire_moved()
        fired = False
        deadline = time.time() + 2
        while time.time() < deadline and not fired:
            fired = cam.frame_changed()
            time.sleep(0.02)
        assert fired is True
        assert cam.frame_changed() is False  # fires once only
    finally:
        cam.stop()


def test_synthetic_source_produces_frames_and_camera_falls_back(runtime, monkeypatch):
    monkeypatch.setenv("BM_NO_CAMERA", "1")
    cam = Camera().start()
    try:
        frame = cam.wait_for_frame(timeout=2)
        assert frame is not None and frame.shape == (720, 1280, 3)
        assert cam.info["source"] == "synthetic"
    finally:
        cam.stop()


def test_module_level_api_signatures():
    import inspect
    assert str(inspect.signature(capture.get_frame)) == "(high_res: bool = False) -> str"
    assert str(inspect.signature(capture.frame_changed)) == "(threshold: float = 0.02) -> bool"


# ---------------------------------------------------------------- camera auto-pick on black frames
class BrightSource(capture.FrameSource):
    def __init__(self, index, level):
        self.index, self.level, self.released = index, level, False

    def read(self):
        return np.full((90, 160, 3), self.level, dtype=np.uint8)

    def release(self):
        self.released = True


def make_opener(levels):
    """levels: {index: brightness} — missing index raises RuntimeError like a closed camera."""
    opened = []

    def opener(i):
        if i not in levels:
            raise RuntimeError(f"camera index {i} did not open")
        src = BrightSource(i, levels[i]); opened.append(src); return src

    opener.opened = opened
    return opener


def test_open_best_camera_keeps_preferred_when_bright(runtime):
    op = make_opener({0: 0, 1: 0, 2: 93})
    src = capture.open_best_camera(2, opener=op)
    assert src.index == 2 and len(op.opened) == 1


def test_open_best_camera_falls_through_black_preferred_to_first_bright(runtime):
    op = make_opener({0: 0, 1: 0, 2: 93})
    src = capture.open_best_camera(0, opener=op)
    assert src.index == 2
    assert op.opened[0].released and op.opened[1].released  # 0 (preferred) and 1 (black) closed
    recs = [json.loads(l) for l in (runtime / "telemetry.jsonl").read_text().splitlines()]
    picks = [r for r in recs if r["stage"] == "camera_pick"]
    assert picks[-1]["index"] == 2 and "first bright" in picks[-1]["reason"]


def test_open_best_camera_prefers_live_phone_over_builtin(runtime):
    op = make_opener({0: 0, 1: 80, 2: 93})
    assert capture.open_best_camera(0, opener=op).index == 1  # first bright index, not the brightest


def test_open_best_camera_unopenable_preferred_and_all_black(runtime):
    op = make_opener({0: 0, 1: 0})
    assert capture.open_best_camera(2, opener=op) is None or capture.open_best_camera(2, opener=op) is None
    op2 = make_opener({0: 0, 1: 0, 2: 0})
    src = capture.open_best_camera(2, opener=op2)
    assert src.index == 2  # all black: keep the preferred one rather than nothing
