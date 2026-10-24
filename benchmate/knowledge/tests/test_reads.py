"""Step 6: reading history — part/page resolution, persistence, ordering, dedupe. No network."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from knowledge import reads
from knowledge.ingestion import load_pages
from knowledge.paths import INDEX_DIR

needs_index = pytest.mark.skipif(not (INDEX_DIR / "bme280.jsonl").is_file(), reason="run knowledge.tools.ingest_all")
BME_URL = "https://www.bosch-sensortec.com/media/boschsensortec/downloads/datasheets/bst-bme280-ds002.pdf"


@pytest.fixture
def reads_file(tmp_path, monkeypatch):
    f = tmp_path / "reads.jsonl"
    monkeypatch.setattr(reads, "READS_FILE", f)
    monkeypatch.setattr(reads, "_ingest_pdf_in_background", lambda url, pid: None)  # never touch the network
    return f


def test_record_read_validates_inputs(reads_file):
    with pytest.raises(ValueError):
        reads.record_read("", "x", 10)
    with pytest.raises(ValueError):
        reads.record_read("https://a.b", 123, 10)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        reads.record_read("https://a.b", None, -1)
    with pytest.raises(ValueError):
        reads.record_read("https://a.b", None, "soon")  # type: ignore[arg-type]


def test_part_id_from_datasheet_url_and_aliases():
    assert reads.resolve_part_id(BME_URL, None) == "bme280"
    assert reads.resolve_part_id("https://docs.espressif.com/esp32-devkitc/user_guide.html", None) == "esp32-devkitc"
    assert reads.resolve_part_id("https://shop.example/GY-BME280-breakout", None) == "bme280"
    assert reads.resolve_part_id("https://en.wikipedia.org/wiki/I%C2%B2C", "The BME280 is a Bosch sensor. BME280 again.") == "bme280"
    assert reads.resolve_part_id("https://example.com/nothing", "plain prose about weather") is None


@needs_index
def test_page_from_fragment_and_from_text():
    assert reads.resolve_page("bme280", BME_URL + "#page=8", None) == "8"
    page_text = load_pages("bme280")["knowledge/datasheets/bme280.pdf"]["13"]
    assert reads.resolve_page("bme280", "https://example.com/notes", page_text) == "13"
    assert reads.resolve_page("bme280", "https://example.com/notes", "too short") is None
    assert reads.resolve_page(None, BME_URL, "anything") is None


@needs_index
def test_record_then_recent_reads_roundtrip(reads_file):
    page_text = load_pages("bme280")["knowledge/datasheets/bme280.pdf"]["8"]
    reads.record_read(BME_URL + "#page=13", None, 45)          # Chrome PDF viewer: no text, fragment only
    reads.record_read("https://example.com/bme280-notes", page_text, 31.5)
    rows = [json.loads(l) for l in reads_file.read_text().splitlines()]
    assert len(rows) == 2 and rows[0]["page"] == "13" and rows[1]["page"] == "8"
    out = reads.recent_reads("bme280")
    assert [r["page"] for r in out] == ["8", "13"]                 # newest first
    assert set(out[0]) == {"part_id", "page", "title", "read_at", "seconds"}
    assert out[0]["seconds"] == 31.5
    assert reads.recent_reads("esp32-devkitc") == []
    assert len(reads.recent_reads()) == 2


def test_recent_reads_merges_progress_reports_and_respects_hours(reads_file):
    old = (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(timespec="seconds")
    reads_file.write_text(json.dumps({"read_at": old, "url": "u", "part_id": "bme280", "page": "8", "title": "t", "seconds": 99}) + "\n")
    reads.record_read("https://x.y/doc", "GY-BME280 module guide", 30)
    reads.record_read("https://x.y/doc", "GY-BME280 module guide", 95)
    out = reads.recent_reads("bme280", hours=24)
    assert len(out) == 1 and out[0]["seconds"] == 95
    assert len(reads.recent_reads("bme280", hours=48)) == 2


def test_recent_reads_empty_without_file(reads_file):
    assert reads.recent_reads() == []


def test_recent_reads_tolerates_bad_lines(reads_file):
    naive = datetime.now().replace(microsecond=0).isoformat()
    reads_file.write_text("\n".join([
        "not json at all",
        json.dumps({"read_at": naive, "url": "u1", "part_id": "bme280", "page": "8", "title": "t", "seconds": None}),
        json.dumps({"read_at": "garbage", "url": "u2", "part_id": "bme280"}),
        json.dumps({"url": "u3"}),
    ]) + "\n")
    out = reads.recent_reads("bme280")
    assert len(out) == 1 and out[0]["seconds"] == 0.0 and out[0]["page"] == "8"


def test_record_read_survives_broken_profiles(reads_file, monkeypatch):
    monkeypatch.setattr(reads, "list_profiles", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    reads.record_read("https://example.com/x", "text", 40)       # must not raise
    out = reads.recent_reads()
    assert len(out) == 1 and out[0]["part_id"] is None


def test_background_ingest_only_for_public_http_pdfs():
    assert reads._is_public_http_pdf("https://vendor.example/a/b.pdf")
    assert not reads._is_public_http_pdf("http://localhost:8000/x.pdf")
    assert not reads._is_public_http_pdf("http://127.0.0.1/x.pdf")
    assert not reads._is_public_http_pdf("http://192.168.1.4/x.pdf")
    assert not reads._is_public_http_pdf("file:///etc/passwd.pdf")
    assert not reads._is_public_http_pdf("/Users/someone/secret.pdf")
    assert not reads._is_public_http_pdf("https://vendor.example/page.html")


def test_pdf_not_yet_indexed_triggers_background_ingest(reads_file, monkeypatch):
    calls = []
    monkeypatch.setattr(reads, "_ingest_pdf_in_background", lambda url, pid: calls.append((url, pid)))
    reads.record_read("https://vendor.example/files/GY-BME280_manual.pdf", None, 40)
    assert calls == [("https://vendor.example/files/GY-BME280_manual.pdf", "bme280")]
    reads.record_read("/Users/someone/GY-BME280.pdf", None, 40)   # local path: resolved but never ingested
    assert len(calls) == 1
