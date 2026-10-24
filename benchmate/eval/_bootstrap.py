"""Make the repo root importable when a script is run as `python eval/xxx.py`."""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

EVAL_DIR = REPO_ROOT / "eval"
TESTSET_DIR = EVAL_DIR / "testset"
HISTORY_CSV = EVAL_DIR / "history.csv"
LAST_RUN_JSON = EVAL_DIR / "last_run.json"
CHART_PNG = EVAL_DIR / "accuracy_journey.png"
HISTORY_COLUMNS = ["timestamp", "note", "component_acc", "wire_acc", "net_acc",
                   "diagnosis_acc", "median_ms", "p90_ms"]
