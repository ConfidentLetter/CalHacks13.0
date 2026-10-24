"""Shared fixtures: mock twins, serial logs, schemas. No network anywhere in this suite."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MOCKS = ROOT / "mocks"


def load_twin(name: str) -> dict:
    return json.loads((MOCKS / f"twin_{name}.json").read_text())


def load_serial(name: str) -> list[str]:
    return (MOCKS / f"serial_{name}.txt").read_text().splitlines()


@pytest.fixture
def twin_ok() -> dict:
    return load_twin("ok")


@pytest.fixture
def twin_5v() -> dict:
    return load_twin("5v")


@pytest.fixture
def twin_swapped() -> dict:
    return load_twin("sda_swapped")


@pytest.fixture
def serial_ok() -> list[str]:
    return load_serial("ok")


@pytest.fixture
def serial_swapped() -> list[str]:
    return load_serial("sda_swapped")


FAKE_HITS = {
    "supply": [
        {"text": "Table 5: Absolute maximum ratings. Voltage at any supply pin VDD and VDDIO pin -0.3 4.25 V.", "page": "9", "section": "Abs max", "score": 0.9, "source_file": "bme280.pdf"},
        {"text": "Electrical specification. Supply voltage VDD: 1.71 V to 3.6 V. Interface supply VDDIO: 1.2 V to 3.6 V.", "page": "22", "section": "Electrical", "score": 0.8, "source_file": "bme280.pdf"},
    ],
    "default": [
        {"text": "The I2C interface uses the following pins: SCK: serial clock (SCL). SDI: data (SDA). CSB must be connected to VDDIO.", "page": "33", "section": "I2C", "score": 0.9, "source_file": "bme280.pdf"},
    ],
}


def fake_search(part_id, query, k=3, budget_ms=None):
    if not part_id or not query:
        return []
    key = "supply" if "supply" in query.lower() or "vdd" in query.lower() else "default"
    return FAKE_HITS[key][:k]


def pytest_configure(config):
    config.addinivalue_line("markers", "realsearch: use T4's live knowledge.search instead of the fake")


@pytest.fixture(autouse=True)
def _fake_knowledge_search(request, monkeypatch):
    """T4's real index loads a model on first search (tens of seconds). Fake it unless marked realsearch."""
    if "realsearch" in request.keywords:
        return
    from reasoning import citations
    monkeypatch.setattr(citations, "safe_search", fake_search)


@pytest.fixture(autouse=True)
def _no_network(monkeypatch, tmp_path):
    """Belt and braces: no test may reach the API by accident, nor pollute runtime/telemetry.jsonl."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("BM_OFFLINE", "1")
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path))
