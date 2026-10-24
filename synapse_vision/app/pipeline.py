"""Glue between the server and the other terminals' modules.

Everything here is synchronous and blocking (model calls, camera reads); the
server runs it in a worker thread. If a module is missing or raises, we fall
back to the mock twin and report it in `twin["_fallback"]` so the viewer and
the Tutor team can see that the data is not real.
"""
from __future__ import annotations

import copy
import json
import os
import shutil
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

from app import telemetry
from app.config import get as cfg

ROOT = Path(__file__).resolve().parent.parent
MOCK_PATH = ROOT / "mocks" / "page_twin_product_rule.json"
SCHEMA_PATH = ROOT / "contracts" / "page_twin.schema.json"
SNAPSHOT_DIR = ROOT / "runtime" / "snapshots"

_validator = Draft202012Validator(json.loads(SCHEMA_PATH.read_text(encoding="utf-8")))


class PipelineError(RuntimeError):
    """Raised with `stage` so the server can report where it failed."""

    def __init__(self, stage: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage


def is_mock() -> bool:
    return os.environ.get("SV_MOCK", "").strip() not in ("", "0", "false", "no")


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def new_snapshot_id(prefix: str = "snap") -> str:
    return f"{prefix}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}"


def validate(twin: dict) -> list[str]:
    """Schema violations as strings; empty means valid."""
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in _validator.iter_errors(twin)]


def mock_twin(previous: dict | None = None, source: str = "mock", original_path: str | None = None) -> dict:
    """The mock page twin with fresh snapshot id and timestamps. Never mutates the file's copy."""
    twin = copy.deepcopy(json.loads(MOCK_PATH.read_text(encoding="utf-8")))
    now = now_iso()
    twin["snapshot_id"] = new_snapshot_id("snap_mock")
    twin["captured_at"] = now
    twin["source"] = source if source in ("pi", "webcam", "upload", "mock") else "mock"
    if previous and previous.get("page_id"):
        twin["page_id"] = previous["page_id"]
    if original_path:
        twin["image"]["original_path"] = original_path
    # Second and later mock snapshots of the same page: nothing new was added.
    if previous and previous.get("page_id") == twin["page_id"] and previous.get("source") == twin["source"]:
        twin["changes"] = {"added": [], "edited": [], "removed": [], "crossed_out": []}
    return twin


def save_upload(filename: str, data: bytes) -> str:
    """Store an uploaded photo under runtime/snapshots/; returns the path relative to repo root."""
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ext = Path(filename or "").suffix.lower() or ".jpg"
    if ext not in (".jpg", ".jpeg", ".png", ".webp", ".heic", ".bmp", ".tif", ".tiff"):
        ext = ".jpg"
    name = f"upload_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid.uuid4().hex[:6]}{ext}"
    p = SNAPSHOT_DIR / name
    p.write_bytes(data)
    return _repo_relative(p)


def _repo_relative(p: Path) -> str:
    """Path relative to the repo root when inside it (so /files/ can serve it), else absolute."""
    try:
        return str(p.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        return str(p.resolve())


_frame_provider = None  # optional callable () -> snapshot path, installed by a process that owns the camera (T5 bridge)


def set_frame_provider(fn) -> None:
    """Let another module (T5's MJPEG streamer) supply stills so the camera is never opened twice.

    `fn()` must return a repo-relative or absolute image path (a fresh full-resolution still), or raise.
    Pass None to go back to capture.get_snapshot.
    """
    global _frame_provider
    _frame_provider = fn


def take_snapshot(source: str | None) -> str:
    """A fresh still: the installed frame provider if any, else T1 capture.get_snapshot. Raises PipelineError('capture', ...)."""
    if _frame_provider is not None:
        with telemetry.timed("capture.snapshot", source="frame_provider"):
            try:
                path = _frame_provider()
            except Exception as exc:  # noqa: BLE001
                raise PipelineError("capture", f"frame provider failed: {type(exc).__name__}: {exc}") from exc
        if not path:
            raise PipelineError("capture", "frame provider returned no frame")
        return str(path)
    try:
        from capture.source import get_snapshot
    except Exception as exc:  # noqa: BLE001 - module missing or half-written
        raise PipelineError("capture", f"capture.source unavailable: {type(exc).__name__}: {exc}") from exc
    with telemetry.timed("capture.snapshot", source=source or cfg("capture.source", "webcam")):
        try:
            return get_snapshot(source)
        except Exception as exc:  # noqa: BLE001
            raise PipelineError("capture", f"get_snapshot failed: {type(exc).__name__}: {exc}") from exc


def wait_for_stable(timeout_s: float) -> str | None:
    """T1 capture.wait_for_stable. Raises PipelineError('capture', ...)."""
    try:
        from capture.source import wait_for_stable as _wait
    except Exception as exc:  # noqa: BLE001
        raise PipelineError("capture", f"capture.source unavailable: {type(exc).__name__}: {exc}") from exc
    try:
        return _wait(timeout_s)
    except Exception as exc:  # noqa: BLE001
        raise PipelineError("capture", f"wait_for_stable failed: {type(exc).__name__}: {exc}") from exc


def build_twin(snapshot_path: str, previous: dict | None, source: str) -> dict:
    """snapshot → page twin. Mock mode or a missing T3 module → mock twin flagged with `_fallback`."""
    t0 = time.perf_counter()
    if is_mock():
        twin = mock_twin(previous, source=source, original_path=snapshot_path)
        twin["_fallback"] = "SV_MOCK=1"
    else:
        try:
            from transcribe import build_page_twin
        except Exception as exc:  # noqa: BLE001
            twin = mock_twin(previous, source=source, original_path=snapshot_path)
            twin["_fallback"] = f"transcribe.build_page_twin unavailable ({type(exc).__name__}: {exc}); serving mock"
        else:
            with telemetry.timed("pipeline.build_page_twin", snapshot=snapshot_path):
                try:
                    twin = build_page_twin(snapshot_path, previous)
                except Exception as exc:  # noqa: BLE001
                    raise PipelineError("transcribe", f"build_page_twin failed: {type(exc).__name__}: {exc}") from exc
    total_ms = (time.perf_counter() - t0) * 1000.0
    twin.setdefault("latency_ms", {})
    twin["latency_ms"]["snapshot_to_twin"] = round(total_ms, 1)
    budget = cfg("budget_ms.snapshot_to_twin_first", 8000)
    telemetry.log("pipeline.snapshot_to_twin", total_ms, snapshot_id=twin.get("snapshot_id"),
                  lines=len(twin.get("lines", [])), over_budget=total_ms > budget)
    errors = validate(twin)
    if errors:
        raise PipelineError("validate", "page twin fails schema: " + "; ".join(errors[:5]))
    return twin


def copy_into_snapshots(path: str) -> str:
    """For `upload:<path>` sources pointing outside runtime/: copy so the viewer can serve it."""
    src = Path(path)
    if not src.is_absolute():
        src = ROOT / src
    try:
        src.resolve().relative_to((ROOT / "runtime").resolve())
        return str(src.resolve().relative_to(ROOT.resolve()))
    except ValueError:
        pass
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    dst = SNAPSHOT_DIR / f"upload_{uuid.uuid4().hex[:8]}{src.suffix.lower() or '.jpg'}"
    shutil.copyfile(src, dst)
    return _repo_relative(dst)
