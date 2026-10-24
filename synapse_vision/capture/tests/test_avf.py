"""AVFoundation-through-ffmpeg source. No camera is touched: ffmpeg is replaced by a tiny frame generator."""
from __future__ import annotations

import os
import stat
import sys
import textwrap
import time

import numpy as np
import pytest

from capture import avf, source
from capture.compat import SourceError

LISTING = textwrap.dedent("""\
    [AVFoundation indev @ 0x800c14140] AVFoundation video devices:
    [AVFoundation indev @ 0x800c14140] [0] MacBook Air相机
    [AVFoundation indev @ 0x800c14140] [1] “Haoze的iPhone”的相机
    [AVFoundation indev @ 0x800c14140] [2] “iPhone”的相机
    [AVFoundation indev @ 0x800c14140] [3] MacBook Air桌上视角相机
    [AVFoundation indev @ 0x800c14140] [4] “Haoze的iPhone”的桌上视角相机
    [AVFoundation indev @ 0x800c14140] [5] “iPhone”的桌上视角相机
    [AVFoundation indev @ 0x800c14140] [6] Capture screen 0
    [AVFoundation indev @ 0x800c14140] AVFoundation audio devices:
    [AVFoundation indev @ 0x800c14140] [0] MacBook Air麦克风
    [AVFoundation indev @ 0x800c14140] [1] ZoomAudioDevice
    [in#0 @ 0x800c14000] Error opening input: Input/output error
""")
MODES = textwrap.dedent("""\
    [in#0 @ 0x7a9014000] Selected framerate (1.000000) is not supported by the device.
    [in#0 @ 0x7a9014000] Supported modes:
    [in#0 @ 0x7a9014000]   640x480@[15.000000 30.000000]fps
    [in#0 @ 0x7a9014000]   1280x720@[15.000000 30.000000]fps
    [in#0 @ 0x7a9014000]   1760x1328@[15.000000 30.000000]fps
""")
DEVICES = avf.parse_devices(LISTING)
W, H = 64, 48


def test_parse_devices_video_only_with_unicode_names():
    assert [d.index for d in DEVICES] == [0, 1, 2, 3, 4, 5, 6]
    assert DEVICES[3].name == "MacBook Air桌上视角相机"
    assert all("麦克风" not in d.name for d in DEVICES), "audio devices must be ignored"


def test_parse_modes_and_best_mode_picks_largest():
    modes = avf.parse_modes(MODES)
    assert len(modes) == 3 and modes[0] == avf.AvfMode(640, 480, 15.0, 30.0)
    assert avf.best_mode(modes) == avf.AvfMode(1760, 1328, 15.0, 30.0)
    assert avf.best_mode(()) is None


@pytest.mark.parametrize("spec,index", [("3", 3), ("MacBook Air桌上视角", 3), ("macbook air相机", 0), ("Capture screen 0", 6)])
def test_resolve_device_by_index_or_name(spec, index):
    assert avf.resolve_device(spec, DEVICES).index == index


@pytest.mark.parametrize("spec,fragment", [("桌上视角", "ambiguous"), ("9", "not found"), ("telepathy", "not found"), ("", "needs a device")])
def test_resolve_device_errors_name_the_candidates(spec, fragment):
    with pytest.raises(SourceError) as exc:
        avf.resolve_device(spec, DEVICES)
    assert fragment in str(exc.value)
    if spec == "桌上视角":
        assert "[3]" in str(exc.value) and "[4]" in str(exc.value) and "[0]" not in str(exc.value)


def test_ffmpeg_bin_prefers_env_then_errors_cleanly(tmp_path, monkeypatch):
    fake = tmp_path / "ffmpeg"
    fake.write_text("#!/bin/sh\nexit 0\n")
    fake.chmod(fake.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("SV_FFMPEG", str(fake))
    assert avf.ffmpeg_bin() == str(fake)
    monkeypatch.delenv("SV_FFMPEG")
    monkeypatch.setattr(avf.shutil, "which", lambda _: None)
    monkeypatch.setattr(avf, "FFMPEG_FALLBACKS", ())
    with pytest.raises(SourceError):
        avf.ffmpeg_bin()


@pytest.fixture
def fake_ffmpeg(tmp_path, monkeypatch):
    """A stand-in 'ffmpeg' that writes 25 raw bgr24 frames (brightness = 10 × frame index) at ~50 fps, then exits."""
    gen = tmp_path / "gen.py"
    gen.write_text(textwrap.dedent(f"""\
        import sys, time
        out = sys.stdout.buffer
        for i in range(25):
            out.write(bytes([min(255, 10 * i)]) * ({W} * {H} * 3)); out.flush(); time.sleep(0.02)
        sys.stderr.write("fake ffmpeg: done\\n")
    """))
    script = tmp_path / "ffmpeg"
    script.write_text(f"#!/bin/sh\nexec {sys.executable} -I {gen} \"$@\"\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setattr(avf, "ffmpeg_bin", lambda: str(script))
    monkeypatch.setattr(avf, "list_devices", lambda ffmpeg=None: DEVICES)
    monkeypatch.setattr(avf, "probe_modes", lambda index, ffmpeg=None: (avf.AvfMode(W, H, 15.0, 30.0),))
    monkeypatch.setattr(avf, "DEFAULTS", {**avf.DEFAULTS, "capture.avf_warmup_s": 0.1})
    monkeypatch.setattr(avf, "cfg", lambda key, default=None: default)
    return script


def test_stream_skips_warmup_serves_fresh_frames_then_reports_end(fake_ffmpeg):
    with avf.AvfStream.open("MacBook Air桌上视角") as stream:
        assert stream.device.index == 3 and (stream.width, stream.height) == (W, H)
        assert "-video_size" in stream.cmd and f"{W}x{H}" in stream.cmd
        first = stream.read(timeout_s=2.0)
        assert first.shape == (H, W, 3)
        assert int(first[0, 0, 0]) >= 30, "frames inside the warm-up window (0.1 s ≈ 5 frames) are discarded"
        second = stream.read(timeout_s=2.0)
        assert int(second[0, 0, 0]) > int(first[0, 0, 0]), "read() never hands out the same frame twice"
        with pytest.raises(SourceError) as exc:
            for _ in range(40):
                stream.read(timeout_s=2.0)
        assert "ended" in str(exc.value) and "fake ffmpeg: done" in str(exc.value)
        assert not stream.alive


def test_stream_read_times_out_when_no_frames_arrive(tmp_path, monkeypatch):
    sleeper = tmp_path / "ffmpeg"
    sleeper.write_text("#!/bin/sh\nsleep 5\n")
    sleeper.chmod(sleeper.stat().st_mode | stat.S_IXUSR)
    stream = avf.AvfStream([str(sleeper)], W, H, avf.AvfDevice(3, "x"), warmup_s=0.0)
    try:
        with pytest.raises(SourceError) as exc:
            stream.read(timeout_s=0.2)
        assert "within 0.2 s" in str(exc.value)
    finally:
        stream.close()
    assert stream._proc.poll() is not None, "close() kills the process"


class _StubStream:
    def __init__(self, frames):
        self._frames = list(frames)

    def read(self, timeout_s=None):
        return self._frames.pop(0) if len(self._frames) > 1 else self._frames[0]

    def close(self):
        pass


def test_get_snapshot_avf_writes_jpeg_under_runtime(monkeypatch):
    frame = np.full((H, W, 3), 200, np.uint8)
    monkeypatch.setattr(source, "_avf", lambda spec: _StubStream([frame]))
    out = source.get_snapshot("avf:3")
    assert out.startswith("runtime/snapshots/") and out.endswith(".jpg")
    assert os.path.getsize(os.path.join(str(avf.__file__).rsplit("/capture/", 1)[0], out)) > 0


def test_plain_avf_source_uses_config_device(monkeypatch):
    seen = []
    frame = np.full((H, W, 3), 200, np.uint8)
    monkeypatch.setattr(avf, "cfg", lambda key, default=None: "“iPhone”的桌上视角相机" if key == "capture.avf_device" else default)
    monkeypatch.setattr(source, "_avf", lambda spec: seen.append(spec) or _StubStream([frame]))
    assert source.get_snapshot("avf").endswith(".jpg")
    source.get_snapshot("avf:3")
    assert seen == ["“iPhone”的桌上视角相机", "3"]


def test_latest_frame_returns_newest_without_waiting_and_live_frame_waits(fake_ffmpeg):
    with avf.AvfStream.open("3") as stream:
        a = stream.latest(timeout_s=2.0)
        b = stream.latest(timeout_s=2.0)
        c = stream.read(timeout_s=2.0)
        assert a.shape == (H, W, 3)
        assert int(b[0, 0, 0]) >= int(a[0, 0, 0]), "latest() never goes backwards"
        assert int(c[0, 0, 0]) > int(b[0, 0, 0]), "read() waits for a frame newer than anything served"


def test_idle_stop_kills_ffmpeg_and_owner_reopens(tmp_path, monkeypatch):
    sleeper = tmp_path / "ffmpeg"
    sleeper.write_text("#!/bin/sh\nsleep 30\n")
    sleeper.chmod(sleeper.stat().st_mode | stat.S_IXUSR)
    opened = []

    def _open(spec, ffmpeg=None):
        s = avf.AvfStream([str(sleeper)], W, H, avf.AvfDevice(3, "x"), warmup_s=0.0, idle_stop_s=0.3)
        opened.append(s)
        return s

    monkeypatch.setattr(avf.AvfStream, "open", staticmethod(_open))
    monkeypatch.setattr(source, "_shared_avf", None)
    first = source._avf("3")
    deadline = time.monotonic() + 3.0
    while first.alive and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not first.alive and first.idle_stopped and first._proc.poll() is not None, "ffmpeg is killed after the idle window"
    with pytest.raises(SourceError) as exc:
        first.read(timeout_s=0.1)
    assert "idle" in str(exc.value)
    second = source._avf("3")
    assert second is not first and second.alive, "a dead stream is replaced on the next use"
    source.release_cameras()
    assert second._proc.poll() is not None


def test_preview_grabber_avf_downscales_to_640_wide(monkeypatch):
    frame = np.zeros((1440, 1920, 3), np.uint8)
    monkeypatch.setattr(source, "_avf", lambda spec: _StubStream([frame]))
    preview = source._preview_grabber("avf:3")()
    assert preview.shape == (480, 640, 3)


def test_latest_frame_and_live_frame_use_shared_avf_stream_and_reject_upload(monkeypatch):
    frame = np.full((H, W, 3), 50, np.uint8)

    class _S(_StubStream):
        def latest(self, timeout_s=None):
            return self._frames[0]

    monkeypatch.setattr(source, "_avf", lambda spec: _S([frame]))
    assert source.latest_frame("avf:MacBook Air桌上视角").shape == (H, W, 3)
    assert source.live_frame("avf").shape == (H, W, 3)
    for fn in (source.latest_frame, source.live_frame):
        with pytest.raises(SourceError):
            fn("upload:/tmp/x.jpg")


def test_release_cameras_closes_shared_stream(monkeypatch):
    closed = []

    class _S(_StubStream):
        def close(self):
            closed.append(True)

    monkeypatch.setattr(source, "_shared_avf", ("avf:3", _S([np.zeros((H, W, 3), np.uint8)])))
    source.release_cameras()
    assert closed == [True] and source._shared_avf is None


@pytest.mark.skipif(not os.environ.get("SV_LIVE_AVF"), reason="set SV_LIVE_AVF=<device index or name> to grab from a real AVFoundation camera")
def test_live_avf_grab_is_not_black():
    with avf.AvfStream.open(os.environ["SV_LIVE_AVF"]) as stream:
        frame = stream.read()
    assert frame.ndim == 3 and frame.shape[1] >= 640
    assert float(frame.mean()) > source.BLACK_FRAME_MEAN
