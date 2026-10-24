import os
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture(autouse=True)
def _isolate_runtime(tmp_path, monkeypatch):
    """Never write to the real runtime/ (telemetry.jsonl, registrations.json) from tests."""
    monkeypatch.setenv("BM_RUNTIME_DIR", str(tmp_path / "runtime"))
    monkeypatch.delenv("BM_MOCK", raising=False)
    monkeypatch.setenv("BM_TIER_B", "0")   # never load OWLv2 in unit tests
    import perception_detect.geometry_bridge as gb
    import perception_detect.registration as reg
    from perception_detect import ocr, twin

    reg.set_current_homography(None)
    gb.set_manual_corners(None)
    gb._last_good_h = None
    ocr.clear_label_cache()
    twin.clear_cache()


@pytest.fixture
def reg_path(tmp_path):
    """Path registrations are written to in this test (already isolated by the autouse fixture)."""
    return tmp_path / "runtime" / "registrations.json"
