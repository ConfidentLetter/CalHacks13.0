import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


@pytest.fixture
def reg_path(tmp_path, monkeypatch):
    """Point registrations at a temp file so tests never touch runtime/."""
    import perception_detect.registration as reg

    p = tmp_path / "registrations.json"
    monkeypatch.setattr(reg, "REGISTRATIONS_PATH", p)
    reg.set_current_homography(None)
    return p
