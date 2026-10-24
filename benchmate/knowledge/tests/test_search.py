"""Step 4 acceptance criteria on the real, committed indexes (knowledge/index/*.jsonl)."""
from __future__ import annotations

import time

import pymupdf
import pytest

from knowledge import search
from knowledge.paths import DATASHEETS_DIR, INDEX_DIR

HIT_KEYS = {"text", "page", "section", "score", "source_file"}
needs_index = pytest.mark.skipif(not (INDEX_DIR / "bme280.jsonl").is_file(), reason="run knowledge.tools.ingest_all")


def _page_text_by_label(pdf: str, label: str) -> str:
    doc = pymupdf.open(str(DATASHEETS_DIR / pdf))
    for i, page in enumerate(doc):
        if (page.get_label() or str(i + 1)) == label:
            return page.get_text()
    raise AssertionError(f"no page labelled {label} in {pdf}")


def _assert_hit_shape(h: dict) -> None:
    assert set(h) == HIT_KEYS
    assert isinstance(h["page"], str) and h["page"]
    assert isinstance(h["score"], float)
    assert 0 < len(h["text"]) <= 1200


@needs_index
def test_bme280_max_supply_voltage_top_hit_and_label():
    hits = search("bme280", "maximum supply voltage", k=3)
    top = hits[0]
    _assert_hit_shape(top)
    assert top["page"] in {"8", "13"}, top  # 8 = operating range (3.6 V), 13 = absolute max (4.25 V)
    assert "VDD" in top["text"]
    assert ("3.6" in top["text"]) or ("4.25" in top["text"])
    # The cited label must be the page a human sees: that page in the PDF really contains the quoted text.
    page_text = _page_text_by_label("bme280.pdf", top["page"])
    assert "VDD" in page_text and ("Absolute maximum ratings" in page_text or "Supply Voltage" in page_text)


@needs_index
def test_bme280_operating_supply_query_hits_page_8():
    hits = search("bme280", "Supply Voltage VDD 1.71 3.6 V electrical parameter specification", k=3)
    assert hits[0]["page"] == "8", [h["page"] for h in hits]
    assert "3.6" in hits[0]["text"]


@needs_index
def test_bme280_i2c_address_mentions_0x76_0x77():
    """The address sentence is split across pages 32/33 of the Bosch PDF: p32 ends '...slave address 1110111
    (0x77), which is the same as' and p33 opens "BMP280's I2C address. The SDO pin...". Both pages are
    correct citations; the hex literals are only on p32. Requirement: hex in the top 3, top hit on 32 or 33."""
    hits = search("bme280", "I2C address", k=3)
    for h in hits:
        _assert_hit_shape(h)
    assert hits[0]["page"] in {"32", "33"}, [h["page"] for h in hits]
    hex_hits = [h for h in hits if "0x76" in h["text"] or "0x77" in h["text"]]
    assert hex_hits, [h["page"] for h in hits]
    assert "0x76" in _page_text_by_label("bme280.pdf", hex_hits[0]["page"])


@needs_index
def test_bme280_sdo_address_query_hits_page_32_top():
    hits = search("bme280", "SDO pin slave address 0x76 0x77", k=3)
    assert hits[0]["page"] == "32" and "0x76" in hits[0]["text"]


@needs_index
def test_esp32_default_i2c_pins_returns_i2c_page():
    hits = search("esp32-devkitc", "default I2C pins", k=3)
    assert hits
    _assert_hit_shape(hits[0])
    assert "I2C" in hits[0]["text"] or "I2C" in hits[0]["section"]
    # NOTE: no Espressif document states GPIO21/22 as *default*; that comes from the Arduino-ESP32 Wire
    # library. The profile roles record that. See NOTES_T4.md.


@needs_index
def test_esp32_header_pins_hit_the_devkitc_guide():
    hits = search("esp32-devkitc", "3V3 5V power supply header pins", k=3)
    assert hits[0]["source_file"].endswith("esp32-devkitc-v4.pdf")


@needs_index
def test_search_latency_under_150ms_after_warmup():
    search("bme280", "warm up", k=1)
    t0 = time.perf_counter()
    for q in ("maximum supply voltage", "I2C address", "SDO pin", "pressure resolution", "GND pin"):
        search("bme280", q, k=5)
    per_query_ms = (time.perf_counter() - t0) * 1000 / 5
    assert per_query_ms <= 150, per_query_ms


@needs_index
def test_search_one_hit_per_page_and_k():
    hits = search("bme280", "I2C", k=5)
    assert len(hits) <= 5
    assert len({(h["source_file"], h["page"]) for h in hits}) == len(hits)


def test_search_unknown_part_returns_empty():
    assert search("no-such-part", "anything") == []
    assert search("bme280", "", k=5) == []
    assert search("bme280", "x", k=0) == []
