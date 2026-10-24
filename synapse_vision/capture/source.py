"""T1 — snapshot sources (pi | webcam | avf[:<device>] | upload:<path>) and the scene-stability trigger.

    python -m capture.source --list        # probe webcam indices 0-5, list ffmpeg/AVFoundation cameras, try the Pi URL
    python -m capture.source --snap        # one full-resolution snapshot from the configured source
    python -m capture.source --wait 30     # block until the scene settles, then snapshot
    python -m capture.source --snap --source "avf:桌上视角"   # macOS Desk View via ffmpeg (see capture/avf.py)
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from capture import avf
from capture.compat import SourceError, cfg, log, repo_relative, runtime_dir, timed

SNAPSHOT_DIR = "snapshots"
DEBUG_DIR = "debug"
PI_TIMEOUT_S = 5.0
PI_RETRIES = 1
WEBCAM_RESOLUTIONS = ((3840, 2160), (2560, 1440), (1920, 1080), (1280, 720))
WEBCAM_WARMUP_FRAMES = 5
PREVIEW_FPS = 5.0
PREVIEW_SIZE = (160, 120)
CLOCK_EPSILON_S = 1e-6
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
BLACK_FRAME_MEAN = 6.0   # a camera that "works" but returns black frames is a virtual/inactive device


__all__ = ["SourceError", "get_snapshot", "wait_for_stable", "latest_frame", "live_frame", "list_sources",
           "release_cameras", "release_webcam"]

# ----------------------------------------------------------------------------- helpers

def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]


def _resolve_source(source: str | None) -> str:
    chosen = source or os.environ.get("SV_SOURCE") or cfg("capture.source", "webcam")
    return str(chosen).strip()


def _snapshot_path(suffix: str = ".jpg") -> Path:
    return runtime_dir(SNAPSHOT_DIR) / f"{_timestamp()}{suffix}"


def _write_jpeg(image: np.ndarray, path: Path, quality: int = 95) -> Path:
    ok = cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise SourceError(f"could not write snapshot to {path}")
    return path


def _http_get(url: str, timeout_s: float = PI_TIMEOUT_S, retries: int = PI_RETRIES) -> bytes:
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(url, timeout=timeout_s) as resp:  # noqa: S310 - local-network camera URL from config
                return resp.read()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last = exc
            if attempt < retries:
                time.sleep(0.3)
    raise SourceError(f"Pi snapshot failed at {url}: {last}")


def _decode(data: bytes, what: str) -> np.ndarray:
    arr = np.frombuffer(data, np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if img is None or img.size == 0:
        raise SourceError(f"{what}: response was not a decodable image ({len(data)} bytes)")
    return img


def _preview_url(snapshot_url: str) -> str:
    base, _, _ = snapshot_url.rpartition("/")
    return f"{base}/preview.jpg"


# ----------------------------------------------------------------------------- upload

def _copy_upload(src: str) -> Path:
    path = Path(src).expanduser()
    if not path.is_file():
        raise SourceError(f"upload source not found: {path}")
    if path.suffix.lower() not in IMAGE_SUFFIXES:
        raise SourceError(f"upload source is not an image: {path}")
    dst = _snapshot_path(path.suffix.lower() if path.suffix.lower() in (".jpg", ".png") else ".jpg")
    if dst.suffix == path.suffix.lower():
        shutil.copyfile(path, dst)
    else:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise SourceError(f"upload source could not be decoded: {path}")
        _write_jpeg(img, dst)
    return dst


# ----------------------------------------------------------------------------- pi

def _pi_snapshot_url() -> str:
    return str(cfg("capture.pi_url", "http://raspberrypi.local:8080/snapshot.jpg"))


def _grab_pi() -> np.ndarray:
    return _decode(_http_get(_pi_snapshot_url()), "pi snapshot")


def _grab_pi_preview() -> np.ndarray:
    return _decode(_http_get(_preview_url(_pi_snapshot_url()), timeout_s=2.0, retries=0), "pi preview")


# ----------------------------------------------------------------------------- webcam

@dataclass
class Webcam:
    """A VideoCapture configured for the highest resolution the camera accepts, with locked exposure/WB."""

    index: int
    cap: cv2.VideoCapture
    width: int
    height: int

    @classmethod
    def open(cls, index: int | None = None) -> "Webcam":
        index = int(cfg("capture.webcam_index", 0)) if index is None else int(index)
        cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            raise SourceError(f"webcam index {index} could not be opened")
        width, height = _request_best_resolution(cap)
        _lock_exposure(cap)
        for _ in range(WEBCAM_WARMUP_FRAMES):
            cap.read()
        return cls(index, cap, width, height)

    def read(self) -> np.ndarray:
        ok, frame = self.cap.read()
        if not ok or frame is None:
            raise SourceError(f"webcam index {self.index} returned no frame")
        return frame

    def close(self) -> None:
        self.cap.release()

    def __enter__(self) -> "Webcam":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _request_best_resolution(cap: cv2.VideoCapture) -> tuple[int, int]:
    for w, h in WEBCAM_RESOLUTIONS:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, w)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, h)
        got_w, got_h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if got_w >= w * 0.9 and got_h >= h * 0.9:
            return got_w, got_h
    return int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))


def _lock_exposure(cap: cv2.VideoCapture) -> None:
    """Best effort: let auto-exposure/WB settle, then freeze them so consecutive frames compare cleanly."""
    try:
        for _ in range(10):
            cap.read()
        cap.set(cv2.CAP_PROP_AUTO_WB, 0)
        cap.set(cv2.CAP_PROP_AUTOFOCUS, 0)
    except cv2.error:
        pass


_shared_webcam: Webcam | None = None


def _webcam() -> Webcam:
    global _shared_webcam
    if _shared_webcam is None:
        _shared_webcam = Webcam.open()
    return _shared_webcam


_shared_avf: tuple[str, avf.AvfStream] | None = None   # (source spec, stream)


def _avf(spec: str) -> avf.AvfStream:
    """Shared ffmpeg stream for `avf:<spec>`; reopened if the device changes or the process died."""
    global _shared_avf
    if _shared_avf is not None and (_shared_avf[0] != spec or not _shared_avf[1].alive):
        _release_avf()
    if _shared_avf is None:
        _shared_avf = (spec, avf.AvfStream.open(spec))
    return _shared_avf[1]


def _release_avf() -> None:
    global _shared_avf
    if _shared_avf is not None:
        _shared_avf[1].close()
        _shared_avf = None


def release_cameras() -> None:
    """Close the shared webcam and the shared ffmpeg stream (call between demos or at shutdown)."""
    global _shared_webcam
    if _shared_webcam is not None:
        _shared_webcam.close()
        _shared_webcam = None
    _release_avf()


release_webcam = release_cameras   # older name


# ----------------------------------------------------------------------------- public API

def get_snapshot(source: str | None = None) -> str:
    """Grab a full-resolution still. source = 'pi' | 'webcam' | 'avf:<device>' | 'upload:<path>' (default from env SV_SOURCE).
    Returns path under runtime/snapshots/."""
    chosen = _resolve_source(source)
    with timed("capture.grab", source=chosen.split(":", 1)[0]):
        if chosen.startswith("upload:"):
            return repo_relative(_copy_upload(chosen[len("upload:"):]))
        if chosen == "upload":
            raise SourceError("source 'upload' needs a path: upload:<path>")
        if chosen == "pi":
            return repo_relative(_write_jpeg(_grab_pi(), _snapshot_path()))
        if chosen == "webcam":
            return repo_relative(_write_jpeg(_webcam().read(), _snapshot_path()))
        if _is_avf(chosen):
            return repo_relative(_write_jpeg(_avf(_avf_spec(chosen)).read(), _snapshot_path()))
    raise SourceError(f"unknown source {chosen!r} (expected pi | webcam | avf | avf:<device> | upload:<path>)")


def _is_avf(source: str) -> bool:
    return source == "avf" or source.startswith("avf:")


def _avf_spec(source: str) -> str:
    """`avf` → device from config capture.avf_device; `avf:<index or name substring>` → that."""
    spec = source[len("avf:"):].strip() if source.startswith("avf:") else ""
    return spec or avf.default_device()


def latest_frame(source: str | None = None) -> np.ndarray:
    """The newest full-resolution BGR frame from the configured live source (webcam | avf | pi) for T5's MJPEG
    grabber: returns at once with whatever the avf stream holds (no wait for a newer frame). Thread-safe for avf
    (one shared ffmpeg process, frames handed out under a lock); an upload source raises."""
    chosen = _resolve_source(source)
    if chosen == "webcam":
        return _webcam().read()
    if _is_avf(chosen):
        return _avf(_avf_spec(chosen)).latest()
    if chosen == "pi":
        return _grab_pi_preview()
    raise SourceError(f"latest_frame needs a live source (webcam | avf | pi), got {chosen!r}")


def live_frame(source: str | None = None) -> np.ndarray:
    """A frame guaranteed newer than the last one handed out (avf), else same as latest_frame."""
    chosen = _resolve_source(source)
    if _is_avf(chosen):
        return _avf(_avf_spec(chosen)).read()
    if chosen == "pi":
        return _grab_pi()
    return latest_frame(chosen)


def _preview_grabber(source: str) -> Callable[[], np.ndarray]:
    if source == "pi":
        return _grab_pi_preview
    if source == "webcam":
        cam = _webcam()
        return lambda: _preview_resize(cam.read())
    if _is_avf(source):
        spec = _avf_spec(source)
        return lambda: _preview_resize(_avf(spec).read())   # _avf() reopens the stream if ffmpeg died
    raise SourceError(f"wait_for_stable needs a live source (pi|webcam|avf), got {source!r}")


def _preview_resize(frame: np.ndarray, width: int = 640) -> np.ndarray:
    h = max(1, round(frame.shape[0] * width / frame.shape[1]))
    return cv2.resize(frame, (width, h), interpolation=cv2.INTER_AREA)


def _small_gray(frame: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if frame.ndim == 3 else frame
    return cv2.resize(gray, PREVIEW_SIZE, interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def frame_diff(a: np.ndarray, b: np.ndarray) -> float:
    """Mean absolute difference between two frames on a 160x120 grayscale, in [0, 1]."""
    return float(np.abs(_small_gray(a) - _small_gray(b)).mean())


class StabilityMonitor:
    """STILL -> CHANGING (diff > threshold) -> STILL_AGAIN (diff < threshold/2 for stable_seconds) -> fire.

    Pure state machine over frames; the clock is injected so tests can drive it deterministically."""

    def __init__(self, change_threshold: float | None = None, stable_seconds: float | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.threshold = float(cfg("capture.change_threshold", 0.02) if change_threshold is None else change_threshold)
        self.stable_seconds = float(cfg("capture.stable_seconds", 1.0) if stable_seconds is None else stable_seconds)
        self.clock = clock
        self.state = "STILL"
        self._prev: np.ndarray | None = None
        self._still_since: float | None = None
        self.last_diff = 0.0

    def update(self, frame: np.ndarray) -> bool:
        """Feed one frame; True exactly when the scene changed and then stayed still long enough."""
        small = _small_gray(frame)
        now = self.clock()
        if self._prev is None:
            self._prev, self._still_since = small, now
            return False
        self.last_diff = float(np.abs(small - self._prev).mean())
        self._prev = small
        if self.last_diff > self.threshold:
            self.state, self._still_since = "CHANGING", None
            return False
        if self.state == "CHANGING":
            if self.last_diff > self.threshold / 2.0:
                self._still_since = None
                return False
            self._still_since = now if self._still_since is None else self._still_since
            if now - self._still_since + CLOCK_EPSILON_S >= self.stable_seconds:
                self.state, self._still_since = "STILL", now
                return True
        return False


def wait_for_stable(timeout_s: float = 30.0) -> str | None:
    """Block until the scene changed and has been still for ~1 s with no hand/pen motion; return a fresh snapshot path, or None on timeout."""
    source = _resolve_source(None)
    if source.startswith("upload"):
        return get_snapshot(source)
    grab = _preview_grabber(source)
    monitor = StabilityMonitor()
    deadline = time.monotonic() + timeout_s
    period = 1.0 / PREVIEW_FPS
    t0 = time.perf_counter()
    while time.monotonic() < deadline:
        tick = time.monotonic()
        try:
            frame = grab()
        except SourceError:
            time.sleep(period)
            continue
        if monitor.update(frame):
            path = get_snapshot(source)
            log("capture.wait_for_stable", (time.perf_counter() - t0) * 1000.0, fired=True)
            return path
        time.sleep(max(0.0, period - (time.monotonic() - tick)))
    log("capture.wait_for_stable", (time.perf_counter() - t0) * 1000.0, fired=False)
    return None


# ----------------------------------------------------------------------------- CLI

def list_sources(max_index: int = 5) -> dict[str, str | None]:
    """Try webcam indices 0..max_index and the Pi URL (one frame each saved to runtime/debug/), and list ffmpeg's
    AVFoundation cameras by name (not grabbed: that would wake every paired iPhone). Returns {name: path|None}."""
    out: dict[str, str | None] = {}
    debug = runtime_dir(DEBUG_DIR)
    for idx in range(max_index + 1):
        try:
            with Webcam.open(idx) as cam:
                frame = cam.read()
                path = debug / f"source_webcam{idx}_{cam.width}x{cam.height}.jpg"
                _write_jpeg(frame, path)
                black = float(frame.mean()) < BLACK_FRAME_MEAN
                out[f"webcam:{idx}"] = f"{repo_relative(path)}{'  (BLACK frame: virtual or inactive camera, do not use)' if black else ''}"
        except SourceError:
            out[f"webcam:{idx}"] = None
    try:
        for dev in avf.list_devices():
            out[f"avf:{dev.index}"] = f"{dev.name}  (ffmpeg/AVFoundation; use --source 'avf:{dev.index}' or a unique name substring)"
    except SourceError as exc:
        out["avf"] = f"not available ({exc})"
    try:
        frame = _grab_pi()
        path = debug / f"source_pi_{frame.shape[1]}x{frame.shape[0]}.jpg"
        _write_jpeg(frame, path)
        out["pi"] = repo_relative(path)
    except SourceError:
        out["pi"] = None
    release_cameras()
    return out


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true", help="probe webcams 0-5, list AVFoundation cameras, try the Pi")
    ap.add_argument("--snap", action="store_true", help="take one snapshot from the configured source")
    ap.add_argument("--wait", type=float, metavar="SECONDS", help="wait for a stable scene, then snapshot")
    ap.add_argument("--source", help="pi | webcam | avf | avf:<device index or name substring> | upload:<path>")
    args = ap.parse_args(argv)
    if args.list:
        for name, path in list_sources().items():
            print(f"{name:>10}: {path or 'not available'}")
        return 0
    if args.wait is not None:
        if args.source:
            os.environ["SV_SOURCE"] = args.source
        print(wait_for_stable(args.wait) or "timeout: scene never changed and settled")
        release_cameras()
        return 0
    print(get_snapshot(args.source))
    release_cameras()
    return 0


if __name__ == "__main__":
    sys.exit(_main())
