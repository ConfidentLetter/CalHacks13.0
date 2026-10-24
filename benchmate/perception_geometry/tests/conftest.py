import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MOCKS = ROOT / "mocks"
CONTRACTS = ROOT / "contracts"


@pytest.fixture(scope="session")
def twin_schema() -> dict:
    return json.loads((CONTRACTS / "twin.schema.json").read_text())


@pytest.fixture(scope="session")
def mock_twins() -> dict[str, dict]:
    return {p.stem: json.loads(p.read_text()) for p in sorted(MOCKS.glob("twin_*.json"))}
