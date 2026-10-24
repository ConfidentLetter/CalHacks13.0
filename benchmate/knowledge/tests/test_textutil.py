"""Unit tests for the pure text helpers (tokenizer, boilerplate, chunking, windows)."""
from __future__ import annotations

from knowledge.textutil import (boilerplate_lines, chunk_page, dedupe_cells, heading_title, matches_heading,
                                parent_window, strip_boilerplate, tokenize)


def test_tokenizer_keeps_hardware_tokens_whole():
    toks = tokenize("VDD max 3.6 V, address 0x76, VDDIO, GPIO21, I²C")
    for want in ("3.6", "0x76", "vddio", "gpio21", "i2c"):
        assert want in toks, toks


def test_tokenizer_adds_subtokens_for_mixed_tokens():
    toks = tokenize("GPIO21")
    assert toks[:3] == ["gpio21", "gpio", "21"]


def test_heading_detection():
    assert heading_title("4.2 Electrical specification")
    assert heading_title("1. Specification")
    assert heading_title("5.3.1 I2C interface")
    assert heading_title("0.2 Pa, equiv. to 1.7 cm") is None
    assert heading_title("9 Target values & not guaranteed | x") is None
    assert heading_title("Parameter") is None


def test_matches_heading_with_or_without_number():
    titles = {"header block", "1.1 general electrical specification"}
    assert matches_heading("Header Block", titles)
    assert matches_heading("2.3 Header Block", titles)
    assert matches_heading("1.1 General electrical specification", titles)
    assert not matches_heading("Header", titles)


def test_boilerplate_removed_only_when_repeated():
    pages = [f"Bosch Sensortec | BME280 Data sheet\n{i} | 10\nunique line {i}" for i in range(10)]
    boiler = boilerplate_lines(pages)
    assert "bosch sensortec | bme280 data sheet" in boiler
    cleaned = strip_boilerplate(pages[3], boiler)
    assert cleaned == "unique line 3"  # footer "3 | 10" removed by pattern, header by frequency


def test_dedupe_cells():
    assert dedupe_cells(["VDD", "VDD", "1.71", "3.6", "3.6", "V"]) == ["VDD", "1.71", "3.6", "V"]


def test_chunk_page_splits_on_headings_and_size():
    text = "1.1 General electrical specification\n" + "\n".join(f"row {i} value {i}" for i in range(120)) \
        + "\n1.2 Humidity parameter specification\nhumidity text"
    chunks = chunk_page(text, max_chars=300)
    assert all(len(body) <= 320 for _, body in chunks)
    sections = [s for s, _ in chunks]
    assert sections[0] == "1.1 General electrical specification"
    assert sections[-1] == "1.2 Humidity parameter specification"
    assert chunks[-1][1].startswith("1.2 Humidity")


def test_chunk_page_with_known_headings_ignores_other_numbered_lines():
    text = "3.6 V max rating\nHeader Block\nJ2 pins"
    chunks = chunk_page(text, known_headings={"header block"}, initial_section="Overview")
    assert [s for s, _ in chunks] == ["Overview", "Header Block"]


def test_parent_window_bounds_and_anchor():
    page = "A" * 2000 + "TARGET CHUNK TEXT HERE" + "B" * 2000
    win = parent_window(page, "TARGET CHUNK TEXT HERE", width=1200)
    assert len(win) <= 1200 and "TARGET CHUNK" in win
    assert parent_window("short page", "x") == "short page"
    assert len(parent_window("Z" * 5000, "not there")) == 1200
