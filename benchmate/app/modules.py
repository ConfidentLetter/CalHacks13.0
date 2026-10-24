"""Safe access to the other terminals' modules (T5).

Every call goes through `call(module, func, mock, *args)`: import the real module lazily, call the
function, and on ImportError / AttributeError / any exception fall back to the mock implementation
and log the fallback. Other terminals' code may be half-written at any moment; the server must
keep serving regardless (AGENTS.md sync protocol).

Also holds the JSON-schema validators for twin / diagnosis.
"""
import copy
import importlib
import json
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import jsonschema

from app.telemetry import REPO_ROOT, log, runtime_dir

MOCKS = REPO_ROOT / "mocks"
CONTRACTS = REPO_ROOT / "contracts"
IDENTITY = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
SCENARIOS = {"ok": "twin_ok", "5v": "twin_5v", "sda_swapped": "twin_sda_swapped"}
SERIAL_FOR_SCENARIO = {"ok": "serial_ok.txt", "5v": "serial_ok.txt", "sda_swapped": "serial_sda_swapped.txt"}

_fallbacks: dict[str, int] = {}
_fallback_lock = threading.Lock()


def new_frame_id() -> str:
    return f"f_{uuid.uuid4().hex[:12]}"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# --------------------------------------------------------------------------- schemas
def _load_schema(name: str) -> jsonschema.Draft202012Validator:
    return jsonschema.Draft202012Validator(json.loads((CONTRACTS / name).read_text()))


TWIN_VALIDATOR = _load_schema("twin.schema.json")
DIAGNOSIS_VALIDATOR = _load_schema("diagnosis.schema.json")


def validation_error(validator: jsonschema.Draft202012Validator, obj: Any) -> str | None:
    """First schema error as a short string, or None if valid."""
    err = jsonschema.exceptions.best_match(validator.iter_errors(obj))
    if err is None:
        return None
    path = "/".join(str(p) for p in err.absolute_path) or "<root>"
    return f"{path}: {err.message}"[:200]


# --------------------------------------------------------------------------- generic dispatcher
def call(module: str, func: str, mock: Callable, *args, **kwargs):
    """Call module.func(*args); on any failure run mock(*args) and log the fallback."""
    t0 = time.perf_counter()
    try:
        mod = importlib.import_module(module)
        fn = getattr(mod, func)
    except Exception as exc:  # module missing or function not yet written
        return _fallback(module, func, mock, f"import: {type(exc).__name__}: {exc}", args, kwargs)
    try:
        return fn(*args, **kwargs)
    except Exception as exc:
        return _fallback(module, func, mock, f"raised: {type(exc).__name__}: {exc}", args, kwargs,
                         ms=(time.perf_counter() - t0) * 1000)


def _fallback(module, func, mock, reason, args, kwargs, ms=0.0):
    key = f"{module}.{func}"
    with _fallback_lock:
        _fallbacks[key] = _fallbacks.get(key, 0) + 1
        count = _fallbacks[key]
    if count <= 3 or count % 50 == 0:  # don't flood the log when a module is down for an hour
        log("fallback", ms, target=key, reason=reason[:160], count=count)
        print(f"[modules] {key} -> mock ({reason[:120]})")
    return mock(*args, **kwargs)


def fallback_counts() -> dict[str, int]:
    with _fallback_lock:
        return dict(_fallbacks)


def warmup() -> dict:
    """Import the other terminals' modules now (they may pull torch etc.) so the first real request
    on stage is not the one paying 5-10 s of import time. Safe to call from a background thread."""
    t0 = time.perf_counter()
    result = {}
    for name in ("perception_geometry", "perception_detect", "knowledge", "reasoning"):
        t = time.perf_counter()
        try:
            importlib.import_module(name)
            result[name] = round((time.perf_counter() - t) * 1000)
        except Exception as exc:
            result[name] = f"{type(exc).__name__}: {exc}"[:80]
    try:  # T3 ships its own warmup (profiles, examples, T4 search index)
        import reasoning
        if hasattr(reasoning, "warmup"):
            t = time.perf_counter()
            reasoning.warmup()
            result["reasoning_warmup"] = round((time.perf_counter() - t) * 1000)
    except Exception as exc:
        result["reasoning_warmup"] = f"{type(exc).__name__}: {exc}"[:80]
    log("warmup", (time.perf_counter() - t0) * 1000, **result)
    return result


# --------------------------------------------------------------------------- mock implementations
def load_mock_twin(scenario: str = "ok", frame_id: str | None = None) -> dict:
    name = SCENARIOS.get(scenario, "twin_ok")
    twin = json.loads((MOCKS / f"{name}.json").read_text())
    twin["frame_id"] = frame_id or new_frame_id()
    twin["timestamp"] = now_iso()
    twin["_mock_scenario"] = scenario  # UI shows a "MOCK" badge; stripped before validation
    return twin


def mock_serial_path(scenario: str) -> str:
    return str(MOCKS / SERIAL_FOR_SCENARIO.get(scenario, "serial_ok.txt"))


def mock_build_twin(frame_path: str) -> dict:
    return load_mock_twin("ok")


def _empty_diagnosis(frame_id: str, mode: str, question: str | None = None) -> dict:
    return {"frame_id": frame_id, "mode": mode, "question": question, "findings": [],
            "needs_user_confirmation": [], "latency_ms": {}}


def _mock_swapped_diagnosis(frame_id: str, mode: str, question: str | None) -> dict:
    d = json.loads((MOCKS / "diagnosis_sda_swapped.json").read_text())
    d.update(frame_id=frame_id, mode=mode, question=question)
    return d


def _looks_swapped(twin: dict) -> bool:
    for net in twin.get("nets", []):
        members = set(net.get("members", []))
        if "bme280_1.SDA" in members and "esp32_1.GPIO22" in members:
            return True
    return False


def mock_run_checks(twin: dict, serial: list[str]) -> dict:
    if _looks_swapped(twin):
        return _mock_swapped_diagnosis(twin["frame_id"], "proactive", None)
    return _empty_diagnosis(twin["frame_id"], "proactive")


def mock_answer(question: str, twin: dict, serial: list[str], frame_path: str) -> dict:
    if _looks_swapped(twin):
        return _mock_swapped_diagnosis(twin["frame_id"], "answer", question)
    d = _empty_diagnosis(twin["frame_id"], "answer", question)
    d["findings"].append({"id": "no_rule", "severity": "info", "title": "No rule matched your question",
                          "explanation": "Rule engine found nothing wrong with the current wiring.",
                          "fix": "Check that the twin overlay matches the board.",
                          "evidence": {}, "confidence": 0.3})
    return d


def mock_refine(question, twin, serial, frame_path, rule_diagnosis) -> dict:
    return rule_diagnosis


def mock_calibrate(frame_path: str, corners=None) -> list[list[float]]:
    return copy.deepcopy(IDENTITY)


def mock_register(part_id: str, row_index: int, pixel) -> None:
    path = runtime_dir() / "registrations.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.loads(path.read_text()) if path.exists() else []
    data.append({"part_id": part_id, "row_index": row_index, "pixel": list(pixel), "ts": now_iso()})
    path.write_text(json.dumps(data, indent=2))


def mock_list_profiles() -> list[dict]:
    try:
        import yaml
        docs = list(yaml.safe_load_all((CONTRACTS / "profile.example.yaml").read_text()))
        return [d for d in docs if isinstance(d, dict) and d.get("part_id")]
    except Exception:
        return [{"part_id": "bme280", "role": "peripheral"}, {"part_id": "esp32-devkitc", "role": "mcu"}]


def mock_record_read(url_or_path: str, text, seconds_on_page: float) -> None:
    path = runtime_dir() / "reads.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as fh:
        fh.write(json.dumps({"url": url_or_path, "chars": len(text or ""), "seconds": seconds_on_page,
                             "ts": now_iso()}) + "\n")


# --------------------------------------------------------------------------- public wrappers
def build_twin(frame_path: str) -> dict:
    return call("perception_detect", "build_twin", mock_build_twin, frame_path)


def run_checks(twin: dict, serial: list[str]) -> dict:
    return call("reasoning", "run_checks", mock_run_checks, twin, serial)


def answer(question: str, twin: dict, serial: list[str], frame_path: str) -> dict:
    return call("reasoning", "answer", mock_answer, question, twin, serial, frame_path)


def refine(question, twin, serial, frame_path, rule_diagnosis) -> dict:
    return call("reasoning", "refine", mock_refine, question, twin, serial, frame_path, rule_diagnosis)


def calibrate(frame_path: str, corners=None):
    return call("perception_geometry", "calibrate", mock_calibrate, frame_path, corners)


def register(part_id: str, row_index: int, pixel) -> None:
    return call("perception_detect", "register", mock_register, part_id, row_index, tuple(pixel))


def list_profiles() -> list[dict]:
    return call("knowledge", "list_profiles", mock_list_profiles)


def record_read(url_or_path: str, text, seconds_on_page: float) -> None:
    return call("knowledge", "record_read", mock_record_read, url_or_path, text, seconds_on_page)
