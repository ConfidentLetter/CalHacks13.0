"""Few-shot example bank loader. Files live in reasoning/examples/*.json (see build_examples.py)."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

EXAMPLES_DIR = Path(__file__).resolve().parent / "examples"


@lru_cache(maxsize=1)
def load_examples() -> tuple[dict[str, Any], ...]:
    out = []
    for p in sorted(EXAMPLES_DIR.glob("*.json")):
        try:
            d = json.loads(p.read_text())
            if {"name", "twin_lines", "diagnosis"} <= set(d):
                out.append(d)
        except Exception:
            continue
    return tuple(out)


def render_examples(examples: tuple[dict[str, Any], ...] | None = None) -> str:
    parts = []
    for ex in (examples if examples is not None else load_examples()):
        diag = {k: ex["diagnosis"][k] for k in ("findings", "needs_user_confirmation") if k in ex["diagnosis"]}
        parts.append(
            f"### Example: {ex['name']}\n"
            f"Twin:\n" + "\n".join(ex["twin_lines"]) + "\n"
            f"Serial:\n" + ("\n".join(ex.get("serial", [])) or "(none)") + "\n"
            f"Question: {ex.get('question') or '(proactive check)'}\n"
            f"Correct output:\n{json.dumps(diag, separators=(',', ':'))}"
        )
    return "\n\n".join(parts) if parts else "(no examples)"
