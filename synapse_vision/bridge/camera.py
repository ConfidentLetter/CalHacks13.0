"""Live camera for the frontend's hardware ("Overhead camera") mode: one grabber thread, MJPEG frames, stills.

Source-agnostic since H+12: every frame comes from T1's public `capture.source.live_frame(spec)`, which owns the one
camera handle per process (webcam → shared `Webcam`, `avf:<device>` → shared ffmpeg AVFoundation stream for macOS
Desk View, pi → HTTP). The bridge never opens a camera itself. While the grabber runs it is installed as T4's frame
provider (`app.pipeline.set_frame_provider`), so `/snapshot`, `/api/camera/capture` and the stream share the handle.
`capture_lock` serialises reads only for the webcam (T1: `Webcam.read()` has no lock; the avf stream is thread-safe).
"""
from __future__ import annotations

import os
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
LIVE_KINDS = ("webcam", "avf", "pi")
KIND_LABELS = {"webcam": "laptop/USB webcam", "avf": "Desk View (macOS AVFoundation via ffmpeg)", "pi": "Raspberry Pi camera"}


class CameraError(RuntimeError):
    """No live frame could be obtained from the configured source."""


# ---------------------------------------------------------------------- which source

def source_spec() -> str:
    """The full source spec T1 understands: `webcam` | `pi` | `avf:<device>` | `upload[:path]`.
    A bare `avf` (Henry's config) is completed with `capture.avf_device`."""
    raw = str(os.environ.get("SV_SOURCE") or cfg("capture.source", "webcam")).strip()
    if raw == "avf":
        device = str(cfg("capture.avf_device", "") or "").strip()
        return f"avf:{device}" if device else "avf"
    return raw


def source_kind(spec: str | None = None) -> str:
    return (spec or source_spec()).split(":", 1)[0]


def source_name() -> str:
    """Short kind for `deviceId` / `camera.source` (`webcam` | `pi` | `avf` | `upload`)."""
    return source_kind()


def source_device(spec: str | None = None) -> str | None:
    spec = spec or source_spec()
    if ":" in spec and source_kind(spec) in ("avf", "upload"):
        return spec.split(":", 1)[1] or None
    if source_kind(spec) == "webcam":
        return f"index {cfg('capture.webcam_index', 0)}"
    if source_kind(spec) == "pi":
        return str(cfg("capture.pi_url", ""))
    return None


def source_detail(spec: str | None = None) -> str:
    spec = spec or source_spec()
    kind = source_kind(spec)
    label = KIND_LABELS.get(kind, kind)
    device = source_device(spec)
    return f"{label}: {device}" if device else label


# ---------------------------------------------------------------------- frames (T1's handle)

def frame_reader(source: str | None = None) -> Callable[[], Any]:
    """A zero-arg callable returning a fresh full-resolution BGR frame from T1's shared source handle."""
    spec = source or source_spec()
    kind = source_kind(spec)
    if kind not in LIVE_KINDS:
        raise CameraError(f"no live camera for source {spec!r} (set capture.source to webcam, pi or avf:<device>)")
    if kind == "avf" and ":" not in spec:
        raise CameraError("source 'avf' needs a device: set capture.avf_device or SV_SOURCE=avf:<name or index>")
    try:
        from capture.source import live_frame
    except Exception as exc:  # noqa: BLE001 - T1 module missing/half-written
        raise CameraError(f"capture.source unavailable: {type(exc).__name__}: {exc}") from exc

    if kind == "webcam":
        def read() -> Any:
            with capture_lock:
                return live_frame(spec)
    else:
        def read() -> Any:
            return live_frame(spec)
    return read


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
    """Is a live camera available? One real frame read per cache window at most (the handle stays open in T1)."""
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
    if os.environ.get("SV_CAMERA_PROBE", "").strip() in ("0", "false", "no"):
        return False, "probe disabled (SV_CAMERA_PROBE=0)"
    spec = source_spec()
    if grabber.running and not grabber.last_error:
        return True, f"{source_detail(spec)} (streaming)"
    t0 = time.perf_counter()
    try:
        reader = grabber.reader or frame_reader(spec)
        frame = reader()
        shape = getattr(frame, "shape", None)
        size = f" {shape[1]}x{shape[0]}" if shape and len(shape) >= 2 else ""
        log("bridge.camera_probe", (time.perf_counter() - t0) * 1000.0, source=source_kind(spec), ok=True)
        return True, f"{source_detail(spec)}{size}"
    except Exception as exc:  # noqa: BLE001 - any failure means "not connected"
        log("bridge.camera_probe", (time.perf_counter() - t0) * 1000.0, source=source_kind(spec), ok=False, error=str(exc))
        return False, f"{source_detail(spec)} — {type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------- grabber

class FrameGrabber:
    """Background thread: reads frames at ~fps from T1's handle, keeps the latest JPEG and the latest full frame."""

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
        period = 1.0 / float(cfg("bridge.stream_fps", DEFAULT_FPS))
        idle_stop = float(cfg("bridge.stream_idle_stop_s", DEFAULT_IDLE_STOP_S))
        reader: Callable[[], Any] | None = None
        while not self._stop.is_set():
            tick = time.monotonic()
            try:
                reader = reader or self.reader or frame_reader()
                frame = reader()
                jpeg = encode_jpeg(frame)
                with self._cond:
                    self._latest_frame, self._latest_jpeg, self._seq = frame, jpeg, self._seq + 1
                    self._cond.notify_all()
                self.last_error = None
            except Exception as exc:  # noqa: BLE001 - keep trying; clients see the last good frame
                self.last_error = f"{type(exc).__name__}: {exc}"
                log("bridge.stream_error", 0.0, error=self.last_error)
                reader = None  # re-resolve the source next round (device may have changed in config)
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
        """A fresh full-resolution still on disk (repo-relative), read through the same source handle."""
        reader = self.reader or frame_reader()
        return write_still(reader())


grabber = FrameGrabber()


def take_still(source: str | None = None) -> tuple[str, str]:
    """One still right now → (repo-relative path, source kind). Same handle as the stream; never a second camera."""
    spec = source or source_spec()
    t0 = time.perf_counter()
    if grabber.reader is None:
        frame_reader(spec)  # validates the source (raises CameraError for upload / bare avf)
    path = grabber.still_path()
    log("bridge.camera_capture", (time.perf_counter() - t0) * 1000.0, source=source_kind(spec))
    return path, source_kind(spec)


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
