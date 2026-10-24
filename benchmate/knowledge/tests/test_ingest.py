"""Ingestion on a real (small) datasheet into a temporary index dir: labels, chunk size, idempotency, embeddings."""
from __future__ import annotations

import json

import numpy as np
import pytest

from knowledge import ingestion as ing
from knowledge import retrieval as srch
from knowledge.paths import DATASHEETS_DIR

SMALL_PDF = DATASHEETS_DIR / "esp32-devkitc-v4.pdf"  # 8 pages, labels 3..10


@pytest.fixture
def tmp_index(tmp_path, monkeypatch):
    monkeypatch.setattr(ing, "INDEX_DIR", tmp_path)
    monkeypatch.setattr(srch, "INDEX_DIR", tmp_path)
    srch.invalidate()
    yield tmp_path
    srch.invalidate()


@pytest.mark.skipif(not SMALL_PDF.is_file(), reason="datasheet not downloaded")
def test_ingest_two_sources_keeps_both_and_aligns_embeddings(tmp_index):
    other = DATASHEETS_DIR / "arduino-uno-pinout.pdf"
    n1 = ing.ingest(str(SMALL_PDF), "tmp-part")
    n2 = ing.ingest(str(other), "tmp-part")
    chunks = ing.load_chunks("tmp-part")
    assert len(chunks) == n1 + n2
    assert len(ing.load_embeddings("tmp-part")) == n1 + n2
    assert set(ing.load_pages("tmp-part")) == {"knowledge/datasheets/esp32-devkitc-v4.pdf",
                                               "knowledge/datasheets/arduino-uno-pinout.pdf"}
    ing.ingest(str(SMALL_PDF), "tmp-part")  # re-ingest one source: counts unchanged
    assert len(ing.load_chunks("tmp-part")) == n1 + n2


@pytest.mark.skipif(not SMALL_PDF.is_file(), reason="datasheet not downloaded")
def test_search_survives_corrupt_pages_file(tmp_index):
    ing.ingest(str(SMALL_PDF), "tmp-part")
    (tmp_index / "tmp-part.pages.json").write_text("{not json")
    srch.invalidate()
    assert srch.search("tmp-part", "power supply", k=2) == []  # degraded, but no exception


@pytest.mark.skipif(not SMALL_PDF.is_file(), reason="datasheet not downloaded")
def test_ingest_real_pdf_labels_chunks_embeddings(tmp_index):
    n = ing.ingest(str(SMALL_PDF), "tmp-part")
    assert n > 10
    chunks = ing.load_chunks("tmp-part")
    assert len(chunks) == n
    assert {c["page"] for c in chunks} <= {str(i) for i in range(3, 11)}, "page labels, not indexes"
    assert all(isinstance(c["page"], str) for c in chunks)
    assert all(len(c["text"]) <= 1000 for c in chunks)
    assert all(set(c) == {"part_id", "page", "page_index", "section", "source_file", "text"} for c in chunks)
    assert any("Header Block" in c["section"] or "J2" == c["section"] for c in chunks), {c["section"] for c in chunks}
    emb = ing.load_embeddings("tmp-part")
    assert emb is not None and emb.shape == (n, 384) and emb.dtype == np.float32
    pages = ing.load_pages("tmp-part")
    assert list(pages) == ["knowledge/datasheets/esp32-devkitc-v4.pdf"]
    assert set(pages["knowledge/datasheets/esp32-devkitc-v4.pdf"]) == {str(i) for i in range(3, 11)}


@pytest.mark.skipif(not SMALL_PDF.is_file(), reason="datasheet not downloaded")
def test_ingest_is_idempotent(tmp_index):
    n1 = ing.ingest(str(SMALL_PDF), "tmp-part")
    rows1 = (tmp_index / "tmp-part.jsonl").read_text()
    n2 = ing.ingest(str(SMALL_PDF), "tmp-part")
    rows2 = (tmp_index / "tmp-part.jsonl").read_text()
    assert n1 == n2 and rows1 == rows2
    assert len(ing.load_embeddings("tmp-part")) == n1


@pytest.mark.skipif(not SMALL_PDF.is_file(), reason="datasheet not downloaded")
def test_ingest_search_roundtrip_header_pins(tmp_index):
    ing.ingest(str(SMALL_PDF), "tmp-part")
    hits = srch.search("tmp-part", "3V3 5V power supply header pins", k=3)
    assert hits and hits[0]["source_file"].endswith("esp32-devkitc-v4.pdf")
    assert any("5V" in h["text"] and "3V3" in h["text"] for h in hits)


def test_ingest_rejects_bad_inputs(tmp_index, tmp_path):
    with pytest.raises(FileNotFoundError):
        ing.ingest(str(tmp_path / "nope.pdf"), "x")
    with pytest.raises(ValueError):
        ing.ingest(str(SMALL_PDF), "../evil")
