"""Tests for app.serial_bridge (Step 3). No real board: fake serial object + replay files."""
import inspect
import time
from types import SimpleNamespace

import pytest

from app import serial_bridge
from app.serial_bridge import SerialBridge, pick_port


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path))
    monkeypatch.delenv("BM_SERIAL_REPLAY", raising=False)
    monkeypatch.delenv("BM_SERIAL_PORT", raising=False)
    return tmp_path


# ---------------------------------------------------------------- port picking
def P(device, description="", hwid=""):
    return SimpleNamespace(device=device, description=description, hwid=hwid)


def test_pick_port_prefers_env_then_usb_like_descriptions():
    ports = [P("/dev/cu.Bluetooth-Incoming-Port", "n/a"), P("/dev/cu.debug-console", "n/a"),
             P("/dev/cu.usbserial-0001", "CP2102N USB to UART Bridge Controller")]
    assert pick_port(ports) == "/dev/cu.usbserial-0001"
    assert pick_port(ports, preferred="/dev/ttyUSB7") == "/dev/ttyUSB7"
    assert pick_port([P("/dev/cu.wchusbserial1420", "USB2.0-Serial")]) == "/dev/cu.wchusbserial1420"
    assert pick_port(ports[:2]) is None
    assert pick_port([]) is None


# ---------------------------------------------------------------- ring buffer / time window
def test_get_recent_serial_filters_by_time_oldest_first(runtime):
    now = {"t": 1000.0}
    b = SerialBridge(clock=lambda: now["t"])
    b.push("old line", ts=980.0)
    b.push("[boot] ESP32 ready", ts=995.0)
    b.push("[i2c] no I2C devices found\r\n", ts=999.0)
    b.push("", ts=999.5)  # blank lines are dropped
    assert b.get_recent_serial(10) == ["[boot] ESP32 ready", "[i2c] no I2C devices found"]
    assert b.get_recent_serial(30) == ["old line", "[boot] ESP32 ready", "[i2c] no I2C devices found"]
    assert b.get_recent_serial(0) == []
    assert b.lines_total == 3


def test_listeners_receive_lines_and_bad_listener_is_isolated(runtime):
    b = SerialBridge()
    seen = []
    b.add_listener(lambda line, ts: seen.append(line))
    b.add_listener(lambda line, ts: 1 / 0)
    b.push("hello")
    assert seen == ["hello"]


# ---------------------------------------------------------------- replay mode
def test_replay_mode_emits_file_lines_and_loops(runtime, tmp_path, monkeypatch):
    f = tmp_path / "serial.txt"
    f.write_text("[boot] ESP32 ready\n[i2c] no I2C devices found\n\n")
    monkeypatch.setenv("BM_SERIAL_REPLAY", str(f))
    monkeypatch.setenv("BM_SERIAL_REPLAY_INTERVAL", "0.01")
    b = SerialBridge().start()
    try:
        deadline = time.time() + 3
        while b.lines_total < 6 and time.time() < deadline:
            time.sleep(0.02)
        assert b.lines_total >= 6, "replay should loop past the 2 file lines"
        recent = b.get_recent_serial(10)
        assert "[boot] ESP32 ready" in recent and "[i2c] no I2C devices found" in recent
        assert b.status()["mode"] == "replay"
    finally:
        b.stop()


def test_set_replay_switches_file_at_runtime(runtime, tmp_path, monkeypatch):
    a, c = tmp_path / "a.txt", tmp_path / "c.txt"
    a.write_text("AAA\n")
    c.write_text("CCC\n")
    monkeypatch.setenv("BM_SERIAL_REPLAY_INTERVAL", "0.01")
    b = SerialBridge()
    b.set_replay(str(a))
    try:
        deadline = time.time() + 2
        while b.lines_total < 2 and time.time() < deadline:
            time.sleep(0.02)
        assert "AAA" in b.get_recent_serial(10)
        b.set_replay(str(c))  # clears buffer and restarts
        deadline = time.time() + 2
        while "CCC" not in b.get_recent_serial(10) and time.time() < deadline:
            time.sleep(0.02)
        recent = b.get_recent_serial(10)
        assert "CCC" in recent and "AAA" not in recent
    finally:
        b.stop()


def test_replay_missing_file_does_not_crash_thread(runtime, monkeypatch):
    monkeypatch.setenv("BM_SERIAL_REPLAY", "/nonexistent/serial.txt")
    b = SerialBridge().start()
    try:
        time.sleep(0.1)
        assert b._thread.is_alive()
        assert b.get_recent_serial(10) == []
    finally:
        b.stop()


# ---------------------------------------------------------------- serial mode with a fake device
class FakeSerial:
    def __init__(self, lines):
        self.lines = list(lines)
        self.closed = False

    def readline(self):
        if not self.lines:
            time.sleep(0.02)
            return b""  # timeout
        return self.lines.pop(0)

    def close(self):
        self.closed = True


def test_serial_mode_reads_decodes_and_strips(runtime, monkeypatch):
    fake = FakeSerial([b"[boot] ESP32 ready\r\n", b"[bme280] T=22.41C\n", b"\xff\xfebad bytes\n"])
    monkeypatch.setattr(serial_bridge, "list_ports",
                        lambda: [P("/dev/cu.usbserial-0001", "CP2102N USB to UART Bridge Controller")])
    b = SerialBridge(serial_factory=lambda port: fake).start()
    try:
        deadline = time.time() + 2
        while b.lines_total < 3 and time.time() < deadline:
            time.sleep(0.02)
        recent = b.get_recent_serial(10)
        assert recent[:2] == ["[boot] ESP32 ready", "[bme280] T=22.41C"]
        assert "bad bytes" in recent[2]
        assert b.port == "/dev/cu.usbserial-0001" and b.status()["mode"] == "serial"
    finally:
        b.stop()
    assert fake.closed


def test_serial_mode_with_no_port_keeps_rescanning(runtime, monkeypatch):
    monkeypatch.setattr(serial_bridge, "list_ports", lambda: [])
    monkeypatch.setattr(serial_bridge, "PORT_RESCAN_SECONDS", 0.05)
    b = SerialBridge().start()
    try:
        time.sleep(0.2)
        assert b._thread.is_alive() and b.port is None
    finally:
        b.stop()


def test_module_level_api_signature():
    assert str(inspect.signature(serial_bridge.get_recent_serial)) == "(seconds: int = 10) -> list[str]"
