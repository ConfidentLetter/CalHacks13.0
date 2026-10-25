"""Accuracy-journey chart from eval/history.csv → eval/accuracy_journey.png (plain style, each point annotated)."""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HISTORY_PATH = ROOT / "eval" / "history.csv"
OUT_PATH = ROOT / "eval" / "accuracy_journey.png"

SERIES = [  # column, label, colour
    ("planted_preservation", "planted-error preservation", "#d0342c"),
    ("exact_match", "line exact match", "#1f5fbf"),
    ("line_recall", "line recall (IoU ≥ 0.6)", "#1a9a4a"),
    ("crossed_out_acc", "crossed-out accuracy", "#d98a00"),
]


def read_history(path: Path = HISTORY_PATH) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def _num(v: str | None) -> float | None:
    try:
        return float(v) if v not in (None, "", "None") else None
    except ValueError:
        return None


def plot(rows: list[dict], out: Path = OUT_PATH, title: str = "StudBud Vision — accuracy journey") -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(11, 5.5), dpi=130)
    xs = list(range(1, len(rows) + 1))
    for col, label, colour in reversed(SERIES):  # headline series drawn last, on top
        ys = [_num(r.get(col)) for r in rows]
        if all(y is None for y in ys):
            continue
        headline = col == "planted_preservation"
        ax.plot(xs, [None if y is None else 100 * y for y in ys], marker="D" if headline else "o", markersize=9 if headline else 6,
                linewidth=3.5 if headline else 1.8, color=colour, label=label, zorder=10 if headline else 2,
                linestyle="-" if headline else "--")
    for x, r in zip(xs, rows):
        y = _num(r.get("planted_preservation"))
        y = 100 * y if y is not None else 0
        ax.annotate(r.get("note", "")[:40], (x, y), textcoords="offset points", xytext=(0, 10), ha="center", fontsize=8,
                    rotation=20, color="#333")
    ax.set_ylim(0, 105)
    ax.set_xticks(xs)
    ax.set_xticklabels([f"run {x}" for x in xs], fontsize=9)
    ax.set_ylabel("%")
    ax.set_title(title, fontsize=13)
    ax.grid(axis="y", color="#ddd")
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    handles, labels = ax.get_legend_handles_labels()
    ax.legend(handles[::-1], labels[::-1], loc="upper center", bbox_to_anchor=(0.5, -0.1), ncol=4, fontsize=9, frameon=False)
    ax.set_ylim(0, 115)
    fig.tight_layout()
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out)
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--history", default=str(HISTORY_PATH))
    p.add_argument("--out", default=str(OUT_PATH))
    a = p.parse_args(argv)
    rows = read_history(Path(a.history))
    if not rows:
        print(f"no rows in {a.history}; run `python -m eval.run_eval --note ...` first")
        return 1
    print("wrote", plot(rows, Path(a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
