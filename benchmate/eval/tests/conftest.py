import sys
from pathlib import Path

EVAL_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = EVAL_DIR.parent
for p in (str(REPO_ROOT), str(EVAL_DIR)):
    if p not in sys.path:
        sys.path.insert(0, p)
