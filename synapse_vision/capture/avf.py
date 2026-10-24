"""T1 — macOS AVFoundation cameras through ffmpeg: source ``avf:<device name or index>``.

Why: macOS "Desk View" virtual cameras (MacBook Air桌上视角相机, iPhone 桌上视角相机) are listed by ffmpeg's
avfoundation backend but are invisible to OpenCV's VideoCapture index enumeration. One ffmpeg process streams
raw BGR frames at a low rate (``capture.avf_fps``, default 5) over a pipe; previews for ``wait_for_stable``
and full-resolution snapshots both come from that one stream, so the device is opened once and auto-exposure
has settled (``capture.avf_warmup_s``) by the time the first frame is returned. The process is restarted by the
owner (``capture.source._avf``) if it dies and stopped after ``capture.avf_idle_stop_s`` without a reader.

    python -m capture.avf                 # list AVFoundation video devices
    python -m capture.source --snap --source avf              # device from config capture.avf_device
    python -m capture.source --snap --source "avf:桌上视角"   # or an explicit unique name substring / index
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import threading
import time
from collections import deque
from dataclasses import dataclass

import cv2
import numpy as np

from capture.compat import SourceError, cfg

FFMPEG_FALLBACKS = ("/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg")
DEFAULTS = {
    "capture.avf_ffmpeg": "ffmpeg",          # H+12 config key (env SV_FFMPEG wins)
    "capture.avf_device": "MacBook Air桌上视角相机",   # used by plain `source: avf`; `avf:<spec>` overrides
    "capture.avf_idle_stop_s": 30.0,         # kill ffmpeg after this long with no reader; reopened on next use
    "capture.avf_fps": 5.0,                  # frames per second delivered over the pipe (previews + snapshots)
    "capture.avf_device_framerate": 30,      # framerate requested from the device (clamped to its supported range)
    "capture.avf_warmup_s": 1.5,             # seconds after the first frame; Desk View auto-exposure settles in ~1.4 s (mean 81 -> 96)
    "capture.avf_frame_timeout_s": 5.0,      # a frame later than this means the device is gone
    "capture.avf_pixel_format": "uyvy422",   # what Apple cameras deliver natively; ffmpeg falls back if unsupported
}
PROBE_TIMEOUT_S = 10.0
STDERR_TAIL_LINES = 8
_DEVICE_LINE = re.compile(r"\[(\d+)\]\s+(.+?)\s*$")
_MODE_LINE = re.compile(r"(\d+)x(\d+)@\[\s*([\d.]+)\s+([\d.]+)\s*\]fps")


def _opt(key: str):
    return cfg(key, DEFAULTS[key])


@dataclass(frozen=True)
class AvfDevice:
    index: int
    name: str


@dataclass(frozen=True)
class AvfMode:
    width: int
    height: int
    fps_min: float
    fps_max: float


# ----------------------------------------------------------------------------- ffmpeg discovery

def ffmpeg_bin() -> str:
    """env SV_FFMPEG → config capture.avf_ffmpeg → PATH → Homebrew locations."""
    candidates = (os.environ.get("SV_FFMPEG"), str(_opt("capture.avf_ffmpeg")), *FFMPEG_FALLBACKS)
    for cand in candidates:
        if not cand:
            continue
        found = shutil.which(cand)
        if found:
            return found
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    raise SourceError("ffmpeg not found: set env SV_FFMPEG or capture.avf_ffmpeg, or `brew install ffmpeg`")


def default_device() -> str:
    return str(_opt("capture.avf_device"))


def parse_devices(text: str) -> tuple[AvfDevice, ...]:
    """Video devices from `ffmpeg -f avfoundation -list_devices true -i ""` output (audio section ignored)."""
    devices: list[AvfDevice] = []
    in_video = False
    for line in text.splitlines():
        if "AVFoundation video devices" in line:
            in_video = True
            continue
        if "AVFoundation audio devices" in line:
            break
        match = _DEVICE_LINE.search(line) if in_video else None
        if match:
            devices.append(AvfDevice(int(match.group(1)), match.group(2)))
    return tuple(devices)


def list_devices(ffmpeg: str | None = None) -> tuple[AvfDevice, ...]:
    cmd = [ffmpeg or ffmpeg_bin(), "-hide_banner", "-f", "avfoundation", "-list_devices", "true", "-i", ""]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"ffmpeg device listing failed: {exc}") from exc
    return parse_devices(proc.stderr + proc.stdout)   # ffmpeg exits non-zero after listing; that is expected


def parse_modes(text: str) -> tuple[AvfMode, ...]:
    return tuple(AvfMode(int(w), int(h), float(lo), float(hi)) for w, h, lo, hi in _MODE_LINE.findall(text))


def probe_modes(index: int, ffmpeg: str | None = None) -> tuple[AvfMode, ...]:
    """Ask for an impossible framerate so ffmpeg prints the device's supported WxH@[fps] modes and exits."""
    cmd = [ffmpeg or ffmpeg_bin(), "-hide_banner", "-f", "avfoundation", "-framerate", "1", "-i", str(index),
           "-frames:v", "1", "-f", "null", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"ffmpeg mode probe failed for device {index}: {exc}") from exc
    return parse_modes(proc.stderr)


def best_mode(modes: tuple[AvfMode, ...]) -> AvfMode | None:
    return max(modes, key=lambda m: m.width * m.height) if modes else None


def resolve_device(spec: str, devices: tuple[AvfDevice, ...]) -> AvfDevice:
    """'3' → device 3; otherwise a case-insensitive exact or unique substring match on the device name."""
    spec = spec.strip()
    if not spec:
        raise SourceError("source 'avf' needs a device: avf:<index> or avf:<name substring>")
    if spec.isdigit():
        for dev in devices:
            if dev.index == int(spec):
                return dev
        raise SourceError(f"avf device index {spec} not found; available: {_describe(devices)}")
    folded = spec.casefold()
    exact = [d for d in devices if d.name.casefold() == folded]
    if len(exact) == 1:
        return exact[0]
    partial = [d for d in devices if folded in d.name.casefold()]
    if len(partial) == 1:
        return partial[0]
    if partial:
        raise SourceError(f"avf device {spec!r} is ambiguous: {_describe(tuple(partial))}")
    raise SourceError(f"avf device {spec!r} not found; available: {_describe(devices)}")


def _describe(devices: tuple[AvfDevice, ...]) -> str:
    return ", ".join(f"[{d.index}] {d.name}" for d in devices) or "(none)"


def _pick_framerate(mode: AvfMode | None) -> float:
    wanted = float(_opt("capture.avf_device_framerate"))
    if mode is None:
        return wanted
    return min(max(wanted, mode.fps_min), mode.fps_max)


# ----------------------------------------------------------------------------- the stream

class AvfStream:
    """One long-lived ffmpeg process delivering bgr24 frames; `read()` always returns a frame newer than the last."""

    def __init__(self, cmd: list[str], width: int, height: int, device: AvfDevice, warmup_s: float,
                 idle_stop_s: float | None = None):
        self.cmd, self.width, self.height, self.device = cmd, width, height, device
        self._warmup_s = warmup_s
        self._idle_stop_s = idle_stop_s
        self._last_used = time.monotonic()
        self._ready_at: float | None = None   # set when the first frame arrives: warm-up counts from there
        self._frame_bytes = width * height * 3
        self._cond = threading.Condition()
        self._latest: np.ndarray | None = None
        self._seq = 0
        self._served = 0
        self._dead = False
        self._stderr: deque[str] = deque(maxlen=STDERR_TAIL_LINES)
        try:
            self._proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        except OSError as exc:
            raise SourceError(f"could not start ffmpeg for {device}: {exc}") from exc
        threading.Thread(target=self._pump_frames, name="avf-frames", daemon=True).start()
        threading.Thread(target=self._pump_stderr, name="avf-stderr", daemon=True).start()
        if idle_stop_s:
            threading.Thread(target=self._idle_watch, name="avf-idle", daemon=True).start()

    @classmethod
    def open(cls, spec: str, ffmpeg: str | None = None) -> "AvfStream":
        ffmpeg = ffmpeg or ffmpeg_bin()
        device = resolve_device(spec, list_devices(ffmpeg))
        mode = best_mode(probe_modes(device.index, ffmpeg))
        framerate = _pick_framerate(mode)
        if mode is None:   # device did not report modes: learn its default frame size from one still
            still = grab_still(device.index, framerate, ffmpeg)
            mode = AvfMode(still.shape[1], still.shape[0], framerate, framerate)
        cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "avfoundation",
               "-framerate", f"{framerate:g}", "-video_size", f"{mode.width}x{mode.height}",
               "-pixel_format", str(_opt("capture.avf_pixel_format")), "-i", str(device.index),
               "-vf", f"fps={float(_opt('capture.avf_fps')):g}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
        return cls(cmd, mode.width, mode.height, device, float(_opt("capture.avf_warmup_s")),
                   idle_stop_s=float(_opt("capture.avf_idle_stop_s")) or None)

    # -- threads
    def _pump_frames(self) -> None:
        out = self._proc.stdout
        while True:
            buf = out.read(self._frame_bytes) if out else b""
            if len(buf) < self._frame_bytes:
                break
            frame = np.frombuffer(buf, np.uint8).reshape(self.height, self.width, 3)
            with self._cond:
                if self._ready_at is None:
                    self._ready_at = time.monotonic() + self._warmup_s
                self._latest, self._seq = frame, self._seq + 1
                self._cond.notify_all()
        with self._cond:
            self._dead = True
            self._cond.notify_all()

    def _pump_stderr(self) -> None:
        err = self._proc.stderr
        for raw in iter(err.readline, b"") if err else ():
            self._stderr.append(raw.decode("utf-8", "replace").rstrip())

    def _idle_watch(self) -> None:
        """Stop ffmpeg when nobody has asked for a frame for `idle_stop_s`; the owner reopens on the next call."""
        assert self._idle_stop_s is not None
        while not self._dead:
            time.sleep(min(1.0, self._idle_stop_s / 4))
            if time.monotonic() - self._last_used >= self._idle_stop_s and not self._dead:
                self.idle_stopped = True
                self.close()
                return

    idle_stopped = False

    # -- API
    def read(self, timeout_s: float | None = None) -> np.ndarray:
        """Next frame not yet handed out, after the warm-up window; raises SourceError if ffmpeg stops."""
        return self._wait_frame(timeout_s, fresh=True)

    def latest(self, timeout_s: float | None = None) -> np.ndarray:
        """The newest frame in memory right now (same frame may be returned twice); waits only for warm-up."""
        return self._wait_frame(timeout_s, fresh=False)

    def _wait_frame(self, timeout_s: float | None, fresh: bool) -> np.ndarray:
        timeout_s = float(_opt("capture.avf_frame_timeout_s")) if timeout_s is None else timeout_s
        deadline = time.monotonic() + timeout_s
        with self._cond:
            self._last_used = time.monotonic()
            while True:
                now = time.monotonic()
                warm = self._ready_at is not None and now >= self._ready_at
                if self._latest is not None and warm and (self._seq > self._served or not fresh):
                    self._served = self._seq
                    return self._latest.copy()
                if self._dead:
                    why = "stopped after idle timeout" if self.idle_stopped else (' | '.join(self._stderr) or 'no output')
                    raise SourceError(f"ffmpeg stream for {self.device} ended: {why}")
                if now >= deadline:
                    raise SourceError(f"no frame from {self.device} within {timeout_s:g} s: {' | '.join(self._stderr)}")
                wake = deadline if self._ready_at is None else min(deadline, max(now, self._ready_at))
                self._cond.wait(timeout=wake - now + 1e-3)

    @property
    def alive(self) -> bool:
        return not self._dead

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.kill()
        try:
            self._proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass

    def __enter__(self) -> "AvfStream":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def grab_still(index: int, framerate: float, ffmpeg: str | None = None) -> np.ndarray:
    """One-shot PNG grab (no warm-up; used only to learn a device's default frame size)."""
    cmd = [ffmpeg or ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-nostdin", "-f", "avfoundation",
           "-framerate", f"{framerate:g}", "-i", str(index), "-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=PROBE_TIMEOUT_S, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise SourceError(f"ffmpeg still grab failed for device {index}: {exc}") from exc
    img = cv2.imdecode(np.frombuffer(proc.stdout, np.uint8), cv2.IMREAD_COLOR) if proc.stdout else None
    if img is None:
        raise SourceError(f"ffmpeg returned no image for device {index}: {proc.stderr.decode('utf-8', 'replace')[-300:]}")
    return img


if __name__ == "__main__":   # pragma: no cover
    for d in list_devices():
        print(f"avf:{d.index}  {d.name}")
