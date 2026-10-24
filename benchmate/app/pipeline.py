"""Pipeline state machine (T5): frame -> twin -> diagnosis, questions, calibration, mock scenarios.

No FastAPI here. Everything is blocking and meant to run in a worker thread; results go out through
`emit(message: dict)` (the server broadcasts them over WebSocket). This keeps the logic unit-testable
with a list as the emit sink.
"""
import json
import threading
import time
from pathlib import Path
from typing import Callable, Optional

from app import modules
from app.telemetry import log, runtime_dir

REFINE_TIMEOUT_S = 8.0
BUDGET_MS = {"twin": 2000, "rules": 300, "refine": 2000}

Emit = Callable[[dict], None]


class Pipeline:
    def __init__(self, emit: Emit, capture=None, serial=None, mock: bool = False,
                 refine_timeout: float = REFINE_TIMEOUT_S):
        self.emit = emit
        self.capture = capture
        self.serial = serial
        self.mock = mock
        self.refine_timeout = refine_timeout
        self.twin: Optional[dict] = None
        self.diagnosis: Optional[dict] = None
        self.homography = None
        self.scenario: Optional[str] = None
        self.last_ms: dict = {}
        self.last_error: Optional[str] = None
        self._busy = threading.Lock()
        self._rerun_wanted = False
        if mock:
            self.scenario = "ok"

    # ------------------------------------------------------------------ helpers
    def status(self, stage: str, ms: float = 0.0, **extra) -> None:
        msg = {"type": "status", "stage": stage, "ms": round(ms, 1)}
        msg.update(extra)
        if "error" in extra:
            self.last_error = f"{stage}: {extra['error']}"
        self.emit(msg)

    def _frame_path(self, high_res: bool) -> Optional[str]:
        if self.capture is None:
            return None
        try:
            return self.capture.get_frame(high_res=high_res)
        except Exception as exc:
            self.status("capture", error=str(exc)[:120])
            return None

    def _serial(self, seconds: int = 10) -> list[str]:
        if self.serial is None:
            return []
        try:
            return self.serial.get_recent_serial(seconds)
        except Exception as exc:
            self.status("serial", error=str(exc)[:120])
            return []

    def _validated(self, kind: str, obj: dict) -> dict:
        validator = modules.TWIN_VALIDATOR if kind == "twin" else modules.DIAGNOSIS_VALIDATOR
        err = modules.validation_error(validator, obj)
        if err:
            self.status(f"{kind}_schema", error=err)
            log(f"{kind}_schema_invalid", 0, error=err)
        return obj

    def _broadcast_twin(self, twin: dict) -> None:
        self.twin = self._validated("twin", twin)
        self.emit({"type": "twin", "twin": twin})

    def _broadcast_diagnosis(self, diag: dict, phase: str) -> None:
        diag.setdefault("latency_ms", {}).update({k: round(v, 1) for k, v in self.last_ms.items()})
        self.diagnosis = self._validated("diagnosis", diag)
        self.emit({"type": "diagnosis", "diagnosis": diag, "phase": phase})
        for req in diag.get("needs_user_confirmation", []) or []:
            self.emit({"type": "confirm_request", "element_id": req.get("element_id"), "prompt": req.get("prompt")})

    # ------------------------------------------------------------------ twin
    def build_twin(self, frame_path: Optional[str]) -> dict:
        t0 = time.perf_counter()
        if self.mock or frame_path is None:
            twin = modules.load_mock_twin(self.scenario or "ok")
        else:
            twin = modules.build_twin(frame_path)
        ms = (time.perf_counter() - t0) * 1000
        self.last_ms = {"twin": ms}
        log("twin", ms, frame_id=twin.get("frame_id"), n_components=len(twin.get("components", [])),
            n_wires=len(twin.get("wires", [])), mock=self.mock)
        self.status("twin", ms, frame_id=twin.get("frame_id"), over_budget=ms > BUDGET_MS["twin"])
        return twin

    # ------------------------------------------------------------------ proactive loop
    def run_proactive(self, frame_path: Optional[str] = None) -> Optional[dict]:
        """Full proactive pass. Returns the diagnosis, or None if another pass was already running."""
        if not self._busy.acquire(blocking=False):
            self._rerun_wanted = True
            return None
        try:
            return self._run_proactive_locked(frame_path)
        except Exception as exc:
            self.status("pipeline", error=f"{type(exc).__name__}: {exc}"[:160])
            return None
        finally:
            self._busy.release()
            if self._rerun_wanted:
                self._rerun_wanted = False
                self.run_proactive()

    def _run_proactive_locked(self, frame_path: Optional[str]) -> dict:
        t_all = time.perf_counter()
        frame_path = frame_path or self._frame_path(high_res=not self.mock)
        twin = self.build_twin(frame_path)
        self._broadcast_twin(twin)
        serial = self._serial(10)
        t0 = time.perf_counter()
        diag = modules.run_checks(twin, serial)
        ms = (time.perf_counter() - t0) * 1000
        self.last_ms["rules"] = ms
        log("rules", ms, frame_id=twin.get("frame_id"), n_findings=len(diag.get("findings", [])), mode="proactive")
        self.status("rules", ms, frame_id=twin.get("frame_id"), over_budget=ms > BUDGET_MS["rules"])
        self._broadcast_diagnosis(diag, phase="rules")
        log("pipeline_total", (time.perf_counter() - t_all) * 1000, frame_id=twin.get("frame_id"))
        return diag

    # ------------------------------------------------------------------ reactive question
    def ask(self, question: str) -> dict:
        """Phase 1 rules (fast), then Phase 2 refine with the same frame_id; refine failure/timeout keeps Phase 1."""
        question = (question or "").strip()
        if not question:
            raise ValueError("empty question")
        with self._busy:
            frame_path = self._frame_path(high_res=not self.mock)
            twin = self.build_twin(frame_path)
            self._broadcast_twin(twin)
            serial = self._serial(10)
            t0 = time.perf_counter()
            phase1 = modules.answer(question, twin, serial, frame_path or "")
            ms = (time.perf_counter() - t0) * 1000
            self.last_ms["rules"] = ms
            log("rules", ms, frame_id=twin.get("frame_id"), mode="answer", question=question[:80])
            self.status("rules", ms, frame_id=twin.get("frame_id"), over_budget=ms > BUDGET_MS["rules"])
            self._broadcast_diagnosis(phase1, phase="rules")

            t0 = time.perf_counter()
            self.status("refine_start", 0, frame_id=twin.get("frame_id"))
            box: dict = {}
            done = threading.Event()

            def _run_refine():
                try:
                    box["result"] = modules.refine(question, twin, serial, frame_path or "", phase1)
                except BaseException as exc:  # noqa: BLE001 - must never kill the thread silently
                    box["error"] = exc
                finally:
                    done.set()
                    if not box.get("consumed"):
                        log("refine_late", (time.perf_counter() - t0) * 1000, frame_id=twin.get("frame_id"))

            threading.Thread(target=_run_refine, name="refine", daemon=True).start()
            try:
                if not done.wait(self.refine_timeout):
                    raise TimeoutError
                box["consumed"] = True
                if "error" in box:
                    raise box["error"]
                refined = box["result"]
                ms = (time.perf_counter() - t0) * 1000
                if not isinstance(refined, dict) or refined.get("frame_id") != phase1.get("frame_id"):
                    raise ValueError("refine returned a diagnosis for a different frame")
                self.last_ms["refine"] = ms
                log("refine", ms, frame_id=twin.get("frame_id"), n_findings=len(refined.get("findings", [])))
                self.status("refine", ms, frame_id=twin.get("frame_id"), over_budget=ms > BUDGET_MS["refine"])
                self._broadcast_diagnosis(refined, phase="refined")
                return refined
            except TimeoutError:
                self.status("refine", (time.perf_counter() - t0) * 1000, error=f"timeout after {self.refine_timeout:.0f}s, keeping rule answer")
                return phase1
            except Exception as exc:
                self.status("refine", (time.perf_counter() - t0) * 1000, error=f"{type(exc).__name__}: {exc}"[:120])
                return phase1

    # ------------------------------------------------------------------ demo backup
    def load_scenario(self, scenario: str) -> dict:
        """Mock keys 1/2/3: load a mock twin + matching serial replay + diagnosis via run_checks."""
        if scenario not in modules.SCENARIOS:
            raise ValueError(f"unknown scenario {scenario!r}; use one of {sorted(modules.SCENARIOS)}")
        self.scenario = scenario
        self.mock = True
        if self.serial is not None:
            try:
                self.serial.set_replay(modules.mock_serial_path(scenario))
            except Exception as exc:
                self.status("serial", error=str(exc)[:120])
        log("mock_scenario", 0, scenario=scenario)
        self.status("mock", 0, scenario=scenario)
        return self.run_proactive() or self.diagnosis or {}

    def set_live(self) -> None:
        """Leave mock mode (key 0): real camera + real serial again."""
        self.mock, self.scenario = False, None
        if self.serial is not None:
            try:
                self.serial.set_serial()
            except Exception as exc:
                self.status("serial", error=str(exc)[:120])
        self.status("live", 0)

    # ------------------------------------------------------------------ interactions
    def calibrate(self, corners=None) -> list:
        from app.markers import detect_marker_ids
        frame_path = self._frame_path(high_res=True) or ""
        t0 = time.perf_counter()
        markers = detect_marker_ids(frame_path) if frame_path else None
        self.homography = modules.calibrate(frame_path, corners)
        ms = (time.perf_counter() - t0) * 1000
        log("calibrate", ms, manual=corners is not None, markers=markers)
        self.status("calibrate", ms, manual=corners is not None, ok=True, markers=markers)
        return self.homography

    def marker_status(self) -> dict:
        """Calibrate-mode helper: how many of the 4 corner markers are visible right now."""
        from app.markers import detect_marker_ids
        frame_path = self._frame_path(high_res=False)
        ids = detect_marker_ids(frame_path) if frame_path else None
        self.status("markers", 0, markers=ids, found=None if ids is None else len(ids))
        return {"markers": ids}

    def register(self, part_id: str, row_index: int, pixel) -> None:
        modules.register(part_id, row_index, pixel)
        self.status("register", 0, part_id=part_id, row_index=row_index)
        self.run_proactive()

    def confirm(self, element_id: str, answer: bool) -> None:
        path = runtime_dir() / "confirmations.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        data = json.loads(path.read_text()) if path.exists() else {}
        data[str(element_id)] = {"answer": bool(answer), "ts": modules.now_iso(),
                                 "frame_id": (self.twin or {}).get("frame_id")}
        path.write_text(json.dumps(data, indent=2))
        log("confirm", 0, element_id=element_id, answer=bool(answer))
        self.status("confirm", 0, element_id=element_id)
        self.run_proactive()

    def snapshot(self) -> dict:
        return {"twin": self.twin, "diagnosis": self.diagnosis, "mock": self.mock, "scenario": self.scenario,
                "last_ms": {k: round(v, 1) for k, v in self.last_ms.items()}, "last_error": self.last_error,
                "fallbacks": modules.fallback_counts(), "budget_ms": BUDGET_MS}
