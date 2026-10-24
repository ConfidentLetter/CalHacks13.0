import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("SV_TELEMETRY", os.path.join(tempfile.gettempdir(), "sv_t3_test_telemetry.jsonl"))

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
