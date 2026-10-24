"""Plot eval/history.csv as the accuracy-journey chart -> eval/accuracy_journey.png.

Usage: python eval/plot_history.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

from _bootstrap import CHART_PNG, HISTORY_CSV  # noqa: E402

SERIES = [("component_acc", "components"), ("wire_acc", "wire endpoints"),
          ("net_acc", "nets"), ("diagnosis_acc", "diagnosis")]


def read_history(path: Path = HISTORY_CSV) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(newline="") as f:
        return list(csv.DictReader(f))


def plot(rows: list[dict], out: Path = CHART_PNG) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(10, 5))
    x = list(range(1, len(rows) + 1))
    for col, label in SERIES:
        ys = [float(r[col]) if r.get(col) else None for r in rows]
        if all(y is None for y in ys):
            continue
        ax.plot(x, ys, marker="o", label=label)
    for i, r in enumerate(rows):
        note = (r.get("note") or "").strip()
        if note:
            ax.annotate(note, (x[i], 1.02), rotation=35, fontsize=7, ha="left", va="bottom",
                        annotation_clip=False)
    ax.set_ylim(0, 1.05)
    ax.set_xlim(0.5, len(rows) + 0.5)
    ax.set_xticks(x)
    ax.set_xlabel("eval run")
    ax.set_ylabel("accuracy")
    ax.set_title("BenchMate accuracy journey", pad=50)
    ax.grid(True, alpha=0.3)
    ax.legend(loc="lower right")
    fig.tight_layout()
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def main() -> int:
    rows = read_history()
    if not rows:
        print(f"{HISTORY_CSV} is empty; run eval/run_eval.py first")
        return 2
    print("wrote", plot(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
