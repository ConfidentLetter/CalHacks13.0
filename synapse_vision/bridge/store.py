"""Reading-memory store: a JSON file under runtime/reading/ (records + screenshot sidecars).

Upsert by id, newest first, one process-wide lock, atomic writes. No database for the demo.
Records are never mutated in place: every operation builds a new list and writes it.
"""
from __future__ import annotations

import base64
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

from bridge.compat import RUNTIME_DIR, now_iso

READING_DIR = Path(os.environ.get("SV_READING_DIR", RUNTIME_DIR / "reading"))
RECORDS_NAME = "records.json"
SHOTS_DIR_NAME = "shots"
MAX_TEXT_CHARS = 4000
MAX_RECORDS = 2000
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,120}$")


class ReadingStore:
    """Thread-safe JSON store for reading records and screenshots."""

    def __init__(self, directory: Path | None = None) -> None:
        self._dir = Path(directory) if directory else None
        self._lock = threading.Lock()
        self._cache: list[dict] | None = None

    # ------------------------------------------------------------------ paths
    @property
    def directory(self) -> Path:
        return self._dir or READING_DIR  # read lazily so tests can repoint READING_DIR

    @property
    def records_path(self) -> Path:
        return self.directory / RECORDS_NAME

    @property
    def shots_dir(self) -> Path:
        return self.directory / SHOTS_DIR_NAME

    # ------------------------------------------------------------------ io
    def _read(self) -> list[dict]:
        if self._cache is not None:
            return self._cache
        try:
            data = json.loads(self.records_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = []
        self._cache = [r for r in data if isinstance(r, dict) and r.get("id")] if isinstance(data, list) else []
        return self._cache

    def _write(self, records: list[dict]) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        tmp = self.records_path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(self.records_path)
        self._cache = records

    # ------------------------------------------------------------------ records
    def upsert(self, record: dict) -> dict:
        """Insert or replace by id; returns the stored (normalized) record."""
        clean = normalize_record(record)
        with self._lock:
            existing = self._read()
            previous = next((r for r in existing if r["id"] == clean["id"]), None)
            merged = {**previous, **clean} if previous else clean
            others = [r for r in existing if r["id"] != clean["id"]]
            self._write(_sorted([merged, *others])[:MAX_RECORDS])
        return merged

    def list(self, limit: int = 100) -> list[dict]:
        with self._lock:
            return [dict(r) for r in self._read()[: max(1, int(limit))]]

    def get(self, record_id: str) -> dict | None:
        with self._lock:
            return next((dict(r) for r in self._read() if r["id"] == record_id), None)

    def delete(self, record_id: str) -> bool:
        with self._lock:
            existing = self._read()
            remaining = [r for r in existing if r["id"] != record_id]
            if len(remaining) != len(existing):
                self._write(remaining)
                return True
            return False

    def clear(self) -> int:
        with self._lock:
            n = len(self._read())
            self._write([])
            return n

    def count_today(self) -> int:
        today = datetime.now().astimezone().date()
        with self._lock:
            return sum(1 for r in self._read() if _local_date(r.get("timestamp")) == today)

    def reset_cache(self) -> None:
        with self._lock:
            self._cache = None

    # ------------------------------------------------------------------ screenshots
    def save_screenshot(self, payload: dict) -> dict:
        """Write the JPEG and a JSON sidecar; idempotent by id. Returns the sidecar record."""
        shot_id = str(payload.get("id") or "").strip()
        if not _SAFE_ID.match(shot_id):
            raise ValueError("screenshot needs a safe 'id'")
        raw = payload.get("imageBase64") or ""
        if not raw:
            raise ValueError("screenshot needs 'imageBase64'")
        try:
            data = base64.b64decode(raw, validate=False)
        except (ValueError, TypeError) as exc:
            raise ValueError("imageBase64 is not valid base64") from exc
        if not data:
            raise ValueError("imageBase64 decoded to nothing")
        record = {k: v for k, v in payload.items() if k != "imageBase64"}
        record["id"] = shot_id
        record["storedAt"] = now_iso()
        record["bytes"] = len(data)
        with self._lock:
            self.shots_dir.mkdir(parents=True, exist_ok=True)
            image_path = self.shots_dir / f"{shot_id}.jpg"
            image_path.write_bytes(data)
            (self.shots_dir / f"{shot_id}.json").write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        record["path"] = str(image_path)
        return record

    def list_screenshots(self, session_id: str | None = None, limit: int = 20) -> list[dict]:
        if not self.shots_dir.exists():
            return []
        out: list[dict] = []
        for p in sorted(self.shots_dir.glob("*.json"), key=lambda q: q.stat().st_mtime, reverse=True):
            try:
                rec = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if session_id and rec.get("sessionId") != session_id:
                continue
            out.append(rec)
            if len(out) >= limit:
                break
        return out

    def recent_screenshots(self, max_age_h: float, limit: int = 20) -> list[dict]:
        """Uploaded screenshots newer than max_age_h whose image file exists, each with its local `path`."""
        cutoff = datetime.now().astimezone().timestamp() - max_age_h * 3600
        out = []
        for rec in self.list_screenshots(limit=limit):
            path = self.shots_dir / f"{rec.get('id')}.jpg"
            try:
                captured = datetime.fromisoformat(str(rec.get("capturedAt") or rec.get("storedAt")).replace("Z", "+00:00"))
            except ValueError:
                continue
            if captured.timestamp() >= cutoff and path.is_file():
                out.append({**rec, "path": str(path)})
        return out


# ---------------------------------------------------------------------- helpers

def normalize_record(record: Any) -> dict:
    """Validate and shape an incoming reading record (extension or dashboard). Raises ValueError."""
    if not isinstance(record, dict):
        raise ValueError("reading record must be a JSON object")
    rid = str(record.get("id") or "").strip()
    if not _SAFE_ID.match(rid):
        raise ValueError("reading record needs a safe 'id' (letters, digits, - _ . :)")
    url = str(record.get("url") or "")
    title = str(record.get("title") or url or "Untitled")
    text = record.get("text")
    out = {k: v for k, v in record.items() if k not in ("text",)}
    out.update({
        "id": rid, "title": title, "url": url,
        "domain": str(record.get("domain") or _domain(url)),
        "timestamp": str(record.get("timestamp") or now_iso()),
        "durationSec": _int(record.get("durationSec", record.get("duration", 0))),
        "source": str(record.get("source") or "manual"),
    })
    if isinstance(text, str) and text:
        out["text"] = text[:MAX_TEXT_CHARS]
    out["excerpt"] = out.get("text") or str(record.get("excerpt") or "")
    return out


def history_item(record: dict) -> dict:
    """The shape GET /api/reading/history returns (text stays out unless the client stored it)."""
    keys = ("id", "title", "url", "domain", "favicon", "startedAt", "timestamp", "durationSec", "source", "excerpt")
    return {k: record.get(k) for k in keys if k in record}


def _sorted(records: list[dict]) -> list[dict]:
    return sorted(records, key=lambda r: str(r.get("timestamp") or ""), reverse=True)


def _int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _domain(url: str) -> str:
    m = re.match(r"^[a-z]+://([^/:]+)", url or "", re.I)
    return (m.group(1) if m else "").removeprefix("www.")


def _local_date(ts: Any):
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).astimezone().date()
    except (TypeError, ValueError):
        return None


_default: ReadingStore | None = None
_default_lock = threading.Lock()


def default_store() -> ReadingStore:
    with _default_lock:
        global _default
        if _default is None:
            _default = ReadingStore()
        return _default
