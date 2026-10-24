"""Speech-to-text for POST /api/tutor/voice: local faster-whisper when importable, else "not built yet" (501).

The model (`bridge.stt_model`, default `base`, CPU int8) loads lazily on first use; `warm()` starts that in a
background thread so the first voice question does not pay the download. SV_STT=0 disables STT entirely.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import threading
import time
from pathlib import Path

from bridge.compat import cfg, log

DEFAULT_MODEL = "base"
_lock = threading.Lock()
_state: dict = {"model": None, "error": None, "warming": False}
_EXT_FOR_MIME = {"audio/webm": ".webm", "audio/mp4": ".m4a", "audio/ogg": ".ogg", "audio/aac": ".aac",
                 "audio/wav": ".wav", "audio/mpeg": ".mp3"}


class STTError(RuntimeError):
    """Transcription failed."""


def enabled() -> bool:
    return os.environ.get("SV_STT", "").strip() not in ("0", "false", "no")


def available() -> bool:
    """True when faster_whisper imports (model may still be loading) and STT is not disabled."""
    if not enabled():
        return False
    try:
        import faster_whisper  # noqa: F401

        return True
    except Exception:  # noqa: BLE001
        return False


def _load():
    with _lock:
        if _state["model"] is not None or _state["error"] is not None:
            return _state["model"]
        t0 = time.perf_counter()
        try:
            from faster_whisper import WhisperModel

            _state["model"] = WhisperModel(str(cfg("bridge.stt_model", DEFAULT_MODEL)), device="cpu", compute_type="int8")
            log("bridge.stt_load", (time.perf_counter() - t0) * 1000.0, model=cfg("bridge.stt_model", DEFAULT_MODEL))
        except Exception as exc:  # noqa: BLE001
            _state["error"] = f"{type(exc).__name__}: {exc}"
            log("bridge.stt_load", (time.perf_counter() - t0) * 1000.0, error=_state["error"])
        return _state["model"]


def warm() -> None:
    """Load the model in a daemon thread (idempotent)."""
    if not available() or _state["model"] is not None or _state["warming"]:
        return
    _state["warming"] = True
    threading.Thread(target=_load, name="bridge-stt-warm", daemon=True).start()


def extension_for(mime: str | None, filename: str | None) -> str:
    base = (mime or "").split(";")[0].strip().lower()
    if base in _EXT_FOR_MIME:
        return _EXT_FOR_MIME[base]
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in _EXT_FOR_MIME.values() else ".webm"


def transcribe(audio: bytes, mime: str | None = None, filename: str | None = None) -> str:
    """Bytes of a browser recording → transcript text. Raises STTError."""
    if not audio:
        raise STTError("empty audio")
    model = _load()
    if model is None:
        raise STTError(_state["error"] or "speech model unavailable")
    tmpdir = tempfile.mkdtemp(prefix="sv_voice_")
    path = Path(tmpdir) / f"question{extension_for(mime, filename)}"
    t0 = time.perf_counter()
    try:
        path.write_bytes(audio)
        segments, info = model.transcribe(str(path), beam_size=int(cfg("bridge.stt_beam_size", 3)), vad_filter=True)
        text = " ".join(s.text.strip() for s in segments).strip()
        log("bridge.stt", (time.perf_counter() - t0) * 1000.0, seconds=round(float(getattr(info, "duration", 0.0)), 1),
            language=getattr(info, "language", None), chars=len(text))
        return text
    except Exception as exc:  # noqa: BLE001
        log("bridge.stt", (time.perf_counter() - t0) * 1000.0, error=f"{type(exc).__name__}: {exc}")
        raise STTError(f"could not transcribe the recording: {type(exc).__name__}: {exc}") from exc
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def status() -> dict:
    return {"available": available(), "loaded": _state["model"] is not None, "error": _state["error"],
            "model": str(cfg("bridge.stt_model", DEFAULT_MODEL)) if available() else None}
