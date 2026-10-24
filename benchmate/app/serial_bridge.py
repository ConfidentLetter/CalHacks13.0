"""Serial bridge (T5, Step 3): the microcontroller's serial output as the second evidence source.

Public contract (contracts/interfaces.md):

    get_recent_serial(seconds=10) -> list[str]   recent lines, oldest first

Modes (picked at start, switchable at runtime for the demo backup):
- serial : pyserial reader thread. Port from env BM_SERIAL_PORT, else the first port whose
           description/device mentions USB, CP210, CH340 or usbserial. 115200 baud. If no port is
           present we keep looking every few seconds, so plugging the board in mid-demo just works.
- replay : env BM_SERIAL_REPLAY=mocks/serial_sda_swapped.txt emits the file's lines one per second,
           looping. Used with no board attached and as the stage backup (mock mode 1/2/3 keys).

Every new line goes to the ring buffer and to listeners (app.server pushes them over WebSocket).
"""
import os
import threading
import time
from collections import deque
from pathlib import Path
from typing import Callable, Iterable, Optional

from app.telemetry import log

BAUD = 115200
RING_SIZE = 2000
PORT_HINTS = ("usb", "cp210", "ch340", "usbserial", "wchusb", "slab")
PORT_RESCAN_SECONDS = 3.0
DEFAULT_REPLAY_INTERVAL = 1.0

Listener = Callable[[str, float], None]


# --------------------------------------------------------------------------- port selection
def pick_port(ports: Iterable, preferred: Optional[str] = None) -> Optional[str]:
    """Choose a serial device path. `ports` are objects with .device and .description
    (serial.tools.list_ports.comports()). Pure function so it is unit-testable."""
    ports = list(ports)
    if preferred:
        return preferred
    for p in ports:
        haystack = f"{getattr(p, 'device', '')} {getattr(p, 'description', '')} {getattr(p, 'hwid', '')}".lower()
        if any(h in haystack for h in PORT_HINTS):
            return p.device
    return None


def list_ports() -> list:
    try:
        from serial.tools import list_ports as lp
        return list(lp.comports())
    except Exception as exc:  # pyserial missing or platform oddity
        log("serial_list_ports", 0, error=str(exc)[:120])
        return []


# --------------------------------------------------------------------------- the bridge
class SerialBridge:
    def __init__(self, clock: Callable[[], float] = time.time,
                 serial_factory: Optional[Callable[[str], object]] = None):
        self._clock = clock
        self._serial_factory = serial_factory or self._open_pyserial
        self._lock = threading.Lock()
        self._ring: deque = deque(maxlen=RING_SIZE)
        self._listeners: list[Listener] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.mode = "idle"
        self.port: Optional[str] = None
        self.replay_path: Optional[str] = None
        self.replay_interval = float(os.environ.get("BM_SERIAL_REPLAY_INTERVAL", DEFAULT_REPLAY_INTERVAL))
        self.lines_total = 0
        self._generation = 0  # bumped whenever the mode changes so the worker thread restarts

    # -- lifecycle
    def start(self) -> "SerialBridge":
        if self._thread and self._thread.is_alive():
            return self
        if self.mode == "idle":
            replay = os.environ.get("BM_SERIAL_REPLAY")
            if replay:
                self.mode, self.replay_path = "replay", replay
            else:
                self.mode, self.port = "serial", os.environ.get("BM_SERIAL_PORT") or None
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="serial", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def set_replay(self, path: str, clear: bool = True) -> None:
        """Switch to replaying `path` (demo backup keys). Restarts the worker."""
        with self._lock:
            self.mode, self.replay_path = "replay", path
            self._generation += 1
            if clear:
                self._ring.clear()
        log("serial_mode", 0, mode="replay", path=path)
        self.start()

    def set_serial(self, port: Optional[str] = None) -> None:
        with self._lock:
            self.mode, self.port = "serial", port
            self._generation += 1
        log("serial_mode", 0, mode="serial", port=port)
        self.start()

    # -- data
    def push(self, line: str, ts: Optional[float] = None) -> None:
        """Record one line (also used by tests and by the server's mock mode)."""
        line = line.rstrip("\r\n")
        if not line:
            return
        ts = self._clock() if ts is None else ts
        with self._lock:
            self._ring.append((ts, line))
            self.lines_total += 1
            listeners = list(self._listeners)
        for cb in listeners:
            try:
                cb(line, ts)
            except Exception as exc:
                print(f"[serial] listener failed: {exc}")

    def get_recent_serial(self, seconds: int = 10) -> list[str]:
        cutoff = self._clock() - seconds
        with self._lock:
            return [line for ts, line in self._ring if ts >= cutoff]

    def add_listener(self, cb: Listener) -> None:
        with self._lock:
            if cb not in self._listeners:
                self._listeners.append(cb)

    def remove_listener(self, cb: Listener) -> None:
        with self._lock:
            if cb in self._listeners:
                self._listeners.remove(cb)

    def status(self) -> dict:
        return {"mode": self.mode, "port": self.port, "replay": self.replay_path,
                "lines_total": self.lines_total}

    # -- worker
    def _run(self) -> None:
        while not self._stop.is_set():
            gen, mode = self._generation, self.mode
            try:
                if mode == "replay":
                    self._run_replay(gen)
                elif mode == "serial":
                    self._run_serial(gen)
                else:
                    time.sleep(0.2)
            except Exception as exc:  # never let the thread die
                log("serial_error", 0, mode=mode, error=f"{type(exc).__name__}: {exc}"[:160])
                time.sleep(0.5)

    def _mode_changed(self, gen: int) -> bool:
        return self._stop.is_set() or gen != self._generation

    def _run_replay(self, gen: int) -> None:
        path = Path(self.replay_path or "")
        if not path.exists():
            log("serial_replay", 0, error=f"replay file not found: {path}")
            self._sleep(2.0, gen)
            return
        lines = [l for l in path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
        if not lines:
            self._sleep(2.0, gen)
            return
        log("serial_replay", 0, path=str(path), n_lines=len(lines))
        while not self._mode_changed(gen):
            for line in lines:
                if self._mode_changed(gen):
                    return
                self.push(line)
                self._sleep(self.replay_interval, gen)

    def _run_serial(self, gen: int) -> None:
        port = pick_port(list_ports(), preferred=self.port)
        if not port:
            self._sleep(PORT_RESCAN_SECONDS, gen)
            return
        try:
            ser = self._serial_factory(port)
        except Exception as exc:
            log("serial_open", 0, port=port, error=str(exc)[:120])
            self._sleep(PORT_RESCAN_SECONDS, gen)
            return
        self.port = port
        log("serial_open", 0, port=port, baud=BAUD)
        try:
            while not self._mode_changed(gen):
                raw = ser.readline()
                if not raw:
                    continue  # timeout, loop to check for mode change
                self.push(raw.decode("utf-8", errors="replace"))
        finally:
            try:
                ser.close()
            except Exception:
                pass
            log("serial_close", 0, port=port)

    def _sleep(self, seconds: float, gen: int) -> None:
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self._mode_changed(gen):
            time.sleep(min(0.05, end - time.monotonic()))

    @staticmethod
    def _open_pyserial(port: str):
        import serial
        return serial.Serial(port, BAUD, timeout=0.5)


# --------------------------------------------------------------------------- module API
_bridge: Optional[SerialBridge] = None
_bridge_lock = threading.Lock()


def bridge() -> SerialBridge:
    """Process-wide bridge singleton (lazily started)."""
    global _bridge
    with _bridge_lock:
        if _bridge is None:
            _bridge = SerialBridge()
        return _bridge.start()


def get_recent_serial(seconds: int = 10) -> list[str]:
    """Recent lines from the microcontroller's serial port, oldest first."""
    return bridge().get_recent_serial(seconds)


def set_replay(path: str, clear: bool = True) -> None:
    """Switch the process-wide bridge to replaying a file (mock scenario keys)."""
    bridge().set_replay(path, clear=clear)


def set_serial(port: Optional[str] = None) -> None:
    """Switch the process-wide bridge back to the real serial port."""
    bridge().set_serial(port)


if __name__ == "__main__":
    print("ports:", [(p.device, p.description) for p in list_ports()])
    b = bridge()
    print("status:", b.status())
    b.add_listener(lambda line, ts: print(f"{time.strftime('%H:%M:%S', time.localtime(ts))}  {line}"))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        b.stop()
