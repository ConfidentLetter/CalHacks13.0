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


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Belt and braces: no test may reach the API by accident."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("BM_OFFLINE", "1")
