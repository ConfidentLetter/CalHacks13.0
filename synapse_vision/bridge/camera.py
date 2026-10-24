"""Live camera for the frontend's hardware mode: one grabber thread, MJPEG frames, stills for everyone.

The camera must be opened once per process. T1 keeps a process-wide `Webcam` singleton
(`capture.source._webcam()`); T4's `/snapshot` reads it from a worker thread. `Webcam.read()` has no lock,
so every read the bridge makes goes through `capture_lock`, and while the grabber runs it installs itself
as T4's frame provider (`app.pipeline.set_frame_provider`) so `/snapshot` takes stills from the same handle.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any, Callable

from bridge.compat import RUNTIME_DIR, cfg, log, new_id, repo_relative

capture_lock = threading.Lock()
BOUNDARY = "frame"
DEFAULT_FPS = 5.0
DEFAULT_MAX_WIDTH = 960
DEFAULT_IDLE_STOP_S = 15.0
DEFAULT_PROBE_CACHE_S = 5.0
SNAPSHOT_DIR = RUNTIME_DIR / "snapshots"


class CameraError(RuntimeError):
    """No live frame could be obtained from the configured source."""


def source_name() -> str:
    import os

    src = os.environ.get("SV_SOURCE") or cfg("capture.source", "webcam")
    return "upload" if str(src).startswith("upload") else str(src)


# ---------------------------------------------------------------------- frame sources (T1 handles)

def _webcam_frame() -> Any:
    """One full-resolution BGR frame from T1's shared webcam (opens it on first use)."""
    from capture.source import _webcam  # T1's process-wide singleton; the only camera handle in the process

    with capture_lock:
        return _webcam().read()


def _pi_frame() -> Any:
    from capture.source import _grab_pi_preview

    return _grab_pi_preview()


def _pi_still_path() -> str:
    from capture.source import get_snapshot

    return get_snapshot("pi")


def frame_reader(source: str | None = None) -> Callable[[], Any]:
    src = source or source_name()
    if src == "webcam":
        return _webcam_frame
    if src == "pi":
        return _pi_frame
    raise CameraError(f"no live camera for source {src!r} (set capture.source to webcam or pi)")


def encode_jpeg(frame: Any, max_width: int | None = None, quality: int = 80) -> bytes:
    import cv2

    width = frame.shape[1]
    limit = int(max_width or cfg("bridge.stream_max_width", DEFAULT_MAX_WIDTH))
    if width > limit:
        scale = limit / width
        frame = cv2.resize(frame, (limit, int(frame.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise CameraError("could not encode frame as JPEG")
    return bytes(buf)


def write_still(frame: Any, prefix: str = "bridge") -> str:
    """Save a full-resolution frame under runtime/snapshots/ and return its repo-relative path."""
    import cv2

    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    path = SNAPSHOT_DIR / f"{new_id(prefix)}.jpg"
    if not cv2.imwrite(str(path), frame, [cv2.IMWRITE_JPEG_QUALITY, 95]):
        raise CameraError(f"could not write still to {path}")
    return repo_relative(path)


# ---------------------------------------------------------------------- probe (for /api/status)

_probe: dict[str, Any] = {"at": 0.0, "value": False, "detail": "not probed"}
_probe_lock = threading.Lock()


def probe_camera(force: bool = False) -> bool:
    """Is a live camera available? Cheap when already open; a real open happens at most once per cache window."""
    ttl = float(cfg("bridge.camera_probe_cache_s", DEFAULT_PROBE_CACHE_S))
    with _probe_lock:
        if not force and time.monotonic() - _probe["at"] < ttl:
            return bool(_probe["value"])
    value, detail = _probe_once()
    with _probe_lock:
        _probe.update(at=time.monotonic(), value=value, detail=detail)
    return value


def probe_detail() -> str:
    with _probe_lock:
        return str(_probe["detail"])


def _probe_once() -> tuple[bool, str]:
    import os

    if os.environ.get("SV_CAMERA_PROBE", "").strip() in ("0", "false", "no"):
        return False, "probe disabled (SV_CAMERA_PROBE=0)"
    if grabber.running:
        return True, "grabber running"
    src = source_name()
    t0 = time.perf_counter()
    try:
        if src == "webcam":
            from capture.source import _shared_webcam, _webcam

            if _shared_webcam is None:
                _webcam()  # opens T1's singleton once; it stays open for /snapshot and the stream
            detail = f"webcam index {cfg('capture.webcam_index', 0)} open"
        elif src == "pi":
            _pi_frame()
            detail = "pi preview reachable"
        else:
            return False, f"source {src!r} is not a live camera"
        log("bridge.camera_probe", (time.perf_counter() - t0) * 1000.0, source=src, ok=True)
        return True, detail
    except Exception as exc:  # noqa: BLE001 - any failure means "not connected"
        log("bridge.camera_probe", (time.perf_counter() - t0) * 1000.0, source=src, ok=False, error=str(exc))
        return False, f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------- grabber

class FrameGrabber:
    """Background thread: reads frames at ~fps, keeps the latest JPEG and the latest full frame."""

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._latest_jpeg: bytes | None = None
        self._latest_frame: Any = None
        self._seq = 0
        self._clients = 0
        self._last_client_at = 0.0
        self.last_error: str | None = None
        self.reader: Callable[[], Any] | None = None  # tests inject a synthetic reader

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def clients(self) -> int:
        return self._clients

    def start(self) -> None:
        with self._cond:
            if self.running:
                return
            self._stop.clear()
            self.last_error = None
            self._thread = threading.Thread(target=self._loop, name="bridge-grabber", daemon=True)
            self._thread.start()
        self._install_provider(True)

    def stop(self) -> None:
        self._stop.set()
        with self._cond:
            self._cond.notify_all()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=3.0)
        self._thread = None
        self._install_provider(False)

    def _install_provider(self, on: bool) -> None:
        try:
            from app import pipeline

            pipeline.set_frame_provider(self.still_path if on else None)
        except Exception:  # noqa: BLE001 - T4 helper missing: /snapshot keeps using capture.get_snapshot
            pass

    def _loop(self) -> None:
        reader = self.reader or frame_reader()
        period = 1.0 / float(cfg("bridge.stream_fps", DEFAULT_FPS))
        idle_stop = float(cfg("bridge.stream_idle_stop_s", DEFAULT_IDLE_STOP_S))
        while not self._stop.is_set():
            tick = time.monotonic()
            try:
                frame = reader()
                jpeg = encode_jpeg(frame)
                with self._cond:
                    self._latest_frame, self._latest_jpeg, self._seq = frame, jpeg, self._seq + 1
                    self._cond.notify_all()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - keep trying; clients see the last good frame
                self.last_error = f"{type(exc).__name__}: {exc}"
                log("bridge.stream_error", 0.0, error=self.last_error)
                time.sleep(min(2.0, period * 4))
            if self._clients == 0 and time.monotonic() - self._last_client_at > idle_stop:
                break
            time.sleep(max(0.0, period - (time.monotonic() - tick)))
        self._thread = None
        self._install_provider(False)

    # ---- clients
    def attach(self) -> None:
        with self._cond:
            self._clients += 1
            self._last_client_at = time.monotonic()
        self.start()

    def detach(self) -> None:
        with self._cond:
            self._clients = max(0, self._clients - 1)
            self._last_client_at = time.monotonic()

    def wait_frame(self, after_seq: int, timeout: float) -> tuple[bytes | None, int]:
        """Block until a frame newer than `after_seq` exists (or timeout); returns (jpeg, seq)."""
        with self._cond:
            self._cond.wait_for(lambda: self._seq > after_seq or self._stop.is_set(), timeout=timeout)
            return self._latest_jpeg, self._seq

    def latest_frame(self) -> Any:
        with self._cond:
            return self._latest_frame

    # ---- stills (also T4's frame provider while running)
    def still_path(self) -> str:
        """A fresh full-resolution still on disk (repo-relative). Reads the camera directly when possible."""
        reader = self.reader or frame_reader()
        frame = reader()
        return write_still(frame)


grabber = FrameGrabber()


def take_still(source: str | None = None) -> tuple[str, str]:
    """One still right now → (repo-relative path, source). Uses the grabber's handle when it is running."""
    src = source or source_name()
    t0 = time.perf_counter()
    if src == "pi" and not grabber.running:
        path = _pi_still_path()
    elif grabber.running or src in ("webcam", "pi"):
        path = grabber.still_path()
    else:
        raise CameraError(f"no live camera for source {src!r}")
    log("bridge.camera_capture", (time.perf_counter() - t0) * 1000.0, source=src)
    return path, src


def mjpeg_part(jpeg: bytes) -> bytes:
    return (f"--{BOUNDARY}\r\nContent-Type: image/jpeg\r\nContent-Length: {len(jpeg)}\r\n\r\n").encode() + jpeg + b"\r\n"


def latest_snapshot_file() -> str | None:
    """Newest still under runtime/snapshots/ (via T4's helper when present)."""
    try:
        from app import bridge_api

        return bridge_api.latest_frame_path()
    except Exception:  # noqa: BLE001
        if not SNAPSHOT_DIR.exists():
            return None
        files = [p for p in SNAPSHOT_DIR.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
        return repo_relative(max(files, key=lambda p: p.stat().st_mtime)) if files else None


def file_mtime_iso(path: str) -> str | None:
    from datetime import datetime, timezone

    p = Path(path)
    if not p.is_absolute():
        from bridge.compat import REPO_ROOT

        p = REPO_ROOT / p
    try:
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).astimezone().isoformat(timespec="seconds")
    except OSError:
        return None
