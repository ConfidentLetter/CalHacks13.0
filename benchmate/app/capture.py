"""Camera capture (T5, Step 2).

Public contract (contracts/interfaces.md):

    get_frame(high_res=False) -> str      path to the latest jpg; high_res grabs a fresh still
    frame_changed(threshold=0.02) -> bool  True once when the scene changed and settled (~0.8 s)

Design:
- One background thread owns cv2.VideoCapture(BM_CAMERA_INDEX). It keeps the newest frame in
  memory, JPEG-encodes it, writes runtime/frames/latest.jpg at ~5 fps (atomic replace) and feeds
  a ChangeDetector state machine on every frame.
- ChangeDetector is a pure class (no camera, no threads) so the "hand has left the frame" logic is
  unit-tested with synthetic frames and a fake clock.
- If the camera cannot be opened, a SyntheticSource draws a placeholder frame so /stream, the UI
  and mock mode keep working. The demo must never die because a webcam went to sleep.

Camera list:  python -m app.capture --list     (tries indices 0-5, saves runtime/frames/probe_<i>.jpg)
"""

import argparse
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import cv2
import numpy as np

from app.telemetry import log, runtime_dir

REQUESTED_W, REQUESTED_H = 1920, 1080
SMALL_W, SMALL_H = 160, 90          # change detection works on a 160x90 grayscale thumbnail
WRITE_INTERVAL_S = 0.2              # latest.jpg at ~5 fps
SETTLE_SECONDS = 0.8                # scene must be still this long before we analyse
JPEG_QUALITY_STREAM = 80
JPEG_QUALITY_STILL = 95
REOPEN_AFTER_FAILURES = 30
MIN_BRIGHTNESS = 5.0                # below this the frame is black (Continuity Camera enumerated but not streaming)
PROBE_INDICES = range(6)


def frames_dir() -> Path:
    return runtime_dir() / "frames"


# --------------------------------------------------------------------------- change detection
def to_small_gray(frame: np.ndarray) -> np.ndarray:
    """BGR frame -> 160x90 float32 grayscale in [0, 1]."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    small = cv2.resize(gray, (SMALL_W, SMALL_H), interpolation=cv2.INTER_AREA)
    return small.astype(np.float32) / 255.0


def mean_abs_diff(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a - b)))


class ChangeDetector:
    """STABLE -(diff vs last analysed > threshold)-> CHANGING
    CHANGING -(consecutive diff < threshold/2 for SETTLE_SECONDS)-> STABLE_NEW (fires once) -> STABLE

    `update(small, now)` returns True exactly once per settled change. The frame that triggered
    True becomes the new "last analysed" reference, so a hand passing through and leaving the
    board unchanged still fires once (the pipeline then sees an identical twin, which is fine).
    """

    STABLE, CHANGING = "STABLE", "CHANGING"

    def __init__(self, threshold: float = 0.02, settle_seconds: float = SETTLE_SECONDS):
        self.threshold = threshold
        self.settle_seconds = settle_seconds
        self.state = self.STABLE
        self.last_analysed: Optional[np.ndarray] = None
        self.prev: Optional[np.ndarray] = None
        self.still_since: Optional[float] = None
        self.last_diff = 0.0

    def update(self, small: np.ndarray, now: float) -> bool:
        if self.last_analysed is None:            # first frame = reference, nothing to report
            self.last_analysed = small
            self.prev = small
            return False
        vs_ref = mean_abs_diff(small, self.last_analysed)
        vs_prev = mean_abs_diff(small, self.prev) if self.prev is not None else 0.0
        self.prev = small
        self.last_diff = vs_ref
        if self.state == self.STABLE:
            if vs_ref > self.threshold:
                self.state = self.CHANGING
                self.still_since = None
            return False
        # CHANGING: wait until consecutive frames are quiet for settle_seconds
        if vs_prev < self.threshold / 2:
            self.still_since = self.still_since if self.still_since is not None else now
            if now - self.still_since >= self.settle_seconds - 1e-6:  # tolerate float drift
                self.state = self.STABLE
                self.still_since = None
                self.last_analysed = small
                return True
        else:
            self.still_since = None
        return False


# --------------------------------------------------------------------------- frame sources
class FrameSource:
    name = "base"

    def read(self) -> Optional[np.ndarray]:
        raise NotImplementedError

    def release(self) -> None:
        pass


class SyntheticSource(FrameSource):
    """Placeholder frames when no camera is available (mock mode / stage fallback)."""

    name = "synthetic"

    def __init__(self, size=(1280, 720), text="NO CAMERA — mock mode"):
        self.size, self.text = size, text

    def read(self) -> np.ndarray:
        w, h = self.size
        frame = np.full((h, w, 3), 38, dtype=np.uint8)
        # a faint breadboard-ish grid so overlay scaling is visible on stage
        for x in range(60, w - 60, 24):
            cv2.line(frame, (x, 80), (x, h - 80), (58, 58, 58), 1)
        for y in range(80, h - 80, 24):
            cv2.line(frame, (60, y), (w - 60, y), (58, 58, 58), 1)
        cv2.putText(frame, self.text, (60, 50), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (200, 200, 200), 2)
        cv2.putText(frame, datetime.now().strftime("%H:%M:%S"), (w - 190, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.9, (120, 120, 120), 2)
        time.sleep(0.05)  # ~20 fps, don't spin
        return frame


class Cv2Source(FrameSource):
    name = "cv2"

    def __init__(self, index: int):
        self.index = index
        backend = cv2.CAP_AVFOUNDATION if sys.platform == "darwin" else cv2.CAP_ANY
        self.cap = cv2.VideoCapture(index, backend)
        if not self.cap.isOpened():
            raise RuntimeError(f"camera index {index} did not open")
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, REQUESTED_W)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, REQUESTED_H)
        self.actual = (int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
        self.locks = self._try_lock_exposure_wb()

    def _try_lock_exposure_wb(self) -> dict:
        """Best effort: not all drivers honour these. We log and move on."""
        results = {}
        for prop, value, key in ((cv2.CAP_PROP_AUTO_EXPOSURE, 0.25, "auto_exposure"),
                                 (cv2.CAP_PROP_AUTO_WB, 0, "auto_wb")):
            try:
                ok = bool(self.cap.set(prop, value))
                results[key] = {"set_ok": ok, "readback": self.cap.get(prop)}
            except cv2.error as exc:  # pragma: no cover - driver specific
                results[key] = {"set_ok": False, "error": str(exc)[:80]}
        return results

    def read(self) -> Optional[np.ndarray]:
        ok, frame = self.cap.read()
        return frame if ok else None

    def release(self) -> None:
        self.cap.release()


def probe_brightness(src: FrameSource, n_frames: int = 8) -> float:
    """Mean pixel value of the last good frame out of n (first frames are often dark). -1 if none."""
    frame = None
    for _ in range(n_frames):
        f = src.read()
        frame = f if f is not None else frame
    return -1.0 if frame is None else float(frame.mean())


def open_best_camera(preferred: int, opener=Cv2Source, candidates=PROBE_INDICES,
                     min_brightness: float = MIN_BRIGHTNESS) -> Optional[FrameSource]:
    """Open `preferred`; if it yields a black frame (a phone's Continuity Camera that is enumerated but
    not streaming), fall through to the first candidate index whose frame is brighter than
    min_brightness. Logs the choice. Returns None if nothing opens."""
    first: Optional[FrameSource] = None
    try:
        first = opener(preferred)
        b = probe_brightness(first)
    except RuntimeError as exc:
        log("camera_pick", 0, index=preferred, error=str(exc)[:100], action="probing others")
        b = -1.0
    if b > min_brightness:
        log("camera_pick", 0, index=preferred, brightness=round(b, 1), reason="BM_CAMERA_INDEX")
        return first
    log("camera_pick", 0, index=preferred, brightness=round(b, 1), reason="black or unopenable, probing others")
    for i in candidates:
        if i == preferred:
            continue
        try:
            src = opener(i)
        except RuntimeError:
            continue
        bi = probe_brightness(src)
        if bi > min_brightness:
            if first is not None:
                first.release()
            log("camera_pick", 0, index=i, brightness=round(bi, 1), reason=f"first bright index (BM_CAMERA_INDEX={preferred} was black)")
            print(f"[capture] BM_CAMERA_INDEX={preferred} gave a black frame; using index {i} (brightness {bi:.1f})")
            return src
        src.release()
    if first is not None:
        log("camera_pick", 0, index=preferred, brightness=round(b, 1), reason="no brighter camera found, keeping it")
    return first


# --------------------------------------------------------------------------- camera thread
class Camera:
    def __init__(self, source_factory: Callable[[], FrameSource] | None = None,
                 clock: Callable[[], float] = time.monotonic, write_files: bool = True):
        self._factory = source_factory or self._default_factory
        self._clock = clock
        self._write_files = write_files
        self._lock = threading.Lock()
        self._frame: Optional[np.ndarray] = None
        self._jpeg: Optional[bytes] = None
        self._frame_seq = 0
        self._new_frame = threading.Condition(self._lock)
        self.detector = ChangeDetector()
        self._changed_flag = False
        self._thread: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self.source: Optional[FrameSource] = None
        self.info: dict = {"source": None, "index": None, "size": None}

    # -- lifecycle
    @staticmethod
    def _default_factory() -> FrameSource:
        index = int(os.environ.get("BM_CAMERA_INDEX", "0"))
        if os.environ.get("BM_NO_CAMERA") == "1":
            return SyntheticSource()
        src = open_best_camera(index)
        if src is None:
            log("camera_open", 0, index=index, error="no camera opened", fallback="synthetic")
            print(f"[capture] no camera opened; using synthetic frames. Try: python -m app.capture --list")
            return SyntheticSource()
        log("camera_open", 0, index=getattr(src, "index", None), requested=[REQUESTED_W, REQUESTED_H],
            actual=list(getattr(src, "actual", (None, None))), locks=getattr(src, "locks", None))
        return src

    def start(self) -> "Camera":
        if self._thread and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="camera", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        if self.source:
            self.source.release()

    def _open(self) -> None:
        self.source = self._factory()
        self.info = {"source": self.source.name, "index": getattr(self.source, "index", None),
                     "size": list(getattr(self.source, "actual", (None, None)))}

    def _run(self) -> None:
        self._open()
        failures, last_write = 0, 0.0
        while not self._stop.is_set():
            frame = self.source.read() if self.source else None
            if frame is None:
                failures += 1
                time.sleep(0.05)
                if failures >= REOPEN_AFTER_FAILURES:
                    log("camera_reopen", 0, failures=failures)
                    try:
                        if self.source:
                            self.source.release()
                    finally:
                        self._open()
                        failures = 0
                continue
            failures = 0
            self._ingest(frame)
            now = self._clock()
            if self._write_files and now - last_write >= WRITE_INTERVAL_S:
                self._write_latest()
                last_write = now

    def _ingest(self, frame: np.ndarray) -> None:
        fired = self.detector.update(to_small_gray(frame), self._clock())
        ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY_STREAM])
        with self._lock:
            self._frame = frame
            self._jpeg = buf.tobytes() if ok else self._jpeg
            self._frame_seq += 1
            if fired:
                self._changed_flag = True
            self._new_frame.notify_all()
        if self.info.get("size") in (None, [None, None]):
            self.info["size"] = [frame.shape[1], frame.shape[0]]

    # -- outputs
    def _write_latest(self) -> None:
        with self._lock:
            jpeg = self._jpeg
        if not jpeg:
            return
        d = frames_dir()
        try:
            d.mkdir(parents=True, exist_ok=True)
            tmp = d / "latest.jpg.tmp"
            tmp.write_bytes(jpeg)
            os.replace(tmp, d / "latest.jpg")  # atomic: readers never see a half file
        except OSError as exc:
            print(f"[capture] cannot write latest.jpg: {exc}")

    def latest_jpeg(self) -> Optional[bytes]:
        with self._lock:
            return self._jpeg

    def latest_frame(self) -> Optional[np.ndarray]:
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def wait_for_frame(self, timeout: float = 3.0, fresh: bool = False) -> Optional[np.ndarray]:
        """Block until a frame exists (fresh=True: until the *next* frame arrives)."""
        with self._lock:
            target = self._frame_seq + (1 if fresh else 0)
            deadline = time.monotonic() + timeout
            while self._frame_seq < target or self._frame is None:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not self._new_frame.wait(remaining):
                    break
            return None if self._frame is None else self._frame.copy()

    def get_frame(self, high_res: bool = False) -> str:
        self.start()
        if not high_res:
            path = frames_dir() / "latest.jpg"
            if not path.exists():
                frame = self.wait_for_frame()
                if frame is not None:
                    self._write_latest()
            return str(path)
        t0 = time.perf_counter()
        frame = self.wait_for_frame(fresh=True)
        if frame is None:
            raise RuntimeError("camera produced no frame within timeout")
        d = frames_dir()
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"still_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]}.jpg"
        cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY_STILL])
        log("capture_still", (time.perf_counter() - t0) * 1000, path=str(path),
            size=[frame.shape[1], frame.shape[0]])
        return str(path)

    def frame_changed(self, threshold: float = 0.02) -> bool:
        self.start()
        self.detector.threshold = threshold
        with self._lock:
            fired, self._changed_flag = self._changed_flag, False
        if fired:
            log("frame_changed", 0, diff=round(self.detector.last_diff, 4), threshold=threshold)
        return fired


# --------------------------------------------------------------------------- module API
_camera: Optional[Camera] = None
_camera_lock = threading.Lock()


def camera() -> Camera:
    """Process-wide camera singleton (lazily started)."""
    global _camera
    with _camera_lock:
        if _camera is None:
            _camera = Camera()
        return _camera.start()


def get_frame(high_res: bool = False) -> str:
    """Path to the latest frame (jpg). high_res=True grabs a fresh full-resolution still."""
    return camera().get_frame(high_res=high_res)


def frame_changed(threshold: float = 0.02) -> bool:
    """True once the scene changed AND has been stable again for ~0.8 s (a hand has left the frame)."""
    return camera().frame_changed(threshold=threshold)


def list_cameras(max_index: int = 5) -> list[dict]:
    """Try indices 0..max_index, save one probe frame each. Phone-as-webcam is often 1 or 2."""
    out = []
    frames_dir().mkdir(parents=True, exist_ok=True)
    for i in range(max_index + 1):
        try:
            src = Cv2Source(i)
        except RuntimeError:
            out.append({"index": i, "ok": False})
            continue
        frame = None
        for _ in range(10):  # first frames are often black while exposure settles
            frame = src.read()
        src.release()
        if frame is None:
            out.append({"index": i, "ok": False, "opened": True})
            continue
        path = frames_dir() / f"probe_{i}.jpg"
        cv2.imwrite(str(path), frame)
        out.append({"index": i, "ok": True, "size": [frame.shape[1], frame.shape[0]],
                    "mean_brightness": round(float(frame.mean()), 1), "path": str(path)})
    return out


def _main() -> None:
    p = argparse.ArgumentParser(description="BenchMate camera tools")
    p.add_argument("--list", action="store_true", help="probe camera indices 0-5")
    p.add_argument("--still", action="store_true", help="grab one high-res still from BM_CAMERA_INDEX")
    a = p.parse_args()
    if a.list:
        for r in list_cameras():
            print(r)
    if a.still:
        print(get_frame(high_res=True))
    if not (a.list or a.still):
        p.print_help()


if __name__ == "__main__":
    _main()
