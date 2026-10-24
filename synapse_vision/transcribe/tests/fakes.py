"""A fake model for tests: answers from the example bank keyed by crop image, counts calls."""
from __future__ import annotations

import json
from pathlib import Path

from transcribe.examples import HERE, load_bank

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "contracts" / "page_twin.schema.json"
CORRECT_PRODUCT_RULE = "\\frac{d}{dx}x^{2}\\sin x=2x\\sin x+x^{2}\\cos x"


def bank_by_image() -> dict[str, dict]:
    return {ex["image_path"]: dict(ex["output"]) for ex in load_bank()}


def example_layout(names: list[str], hints: dict[str, str] | None = None) -> dict:
    """A layout whose crops are the example PNGs, stacked top to bottom on a fake 1700x2200 page."""
    hints = hints or {}
    lines = []
    for i, name in enumerate(names):
        p = str(HERE / f"{name}.png")
        lines.append({"order": i, "region_id": "R1", "bbox": [130.0, 300.0 + 140.0 * i, 900.0, 100.0],
                      "crop_path": p, "context_crop_path": p, "status_hint": hints.get(name, "active"),
                      "ink_density": None})
    return {"regions": [{"id": "R1", "type": "work", "bbox": [120, 280, 1460, 1500]}], "lines": lines,
            "quality": {"ok": True, "issues": []}}


class FakeModel:
    """Install with `fake.install(monkeypatch)`; configure per-test overrides on the attributes."""

    def __init__(self):
        self.by_image = bank_by_image()
        self.page_override: dict[str, dict] = {}   # image path -> page-pass reading
        self.reread_choice = "A"
        self.reread_own: dict | None = None
        self.crossed_answer = True
        self.calls = {"page": 0, "line": 0, "reread": 0, "crossed": 0}
        self.reread_args: list[tuple] = []
        self.tiles: list[str] = []

    def install(self, monkeypatch, tiles: list[str]):
        import transcribe.page as page_mod

        self.tiles = tiles
        monkeypatch.setattr(page_mod, "get_tiles", lambda path: [{"path": t, "bbox": None} for t in tiles])
        monkeypatch.setattr(page_mod, "page_pass", self.page_pass)
        monkeypatch.setattr(page_mod, "line_pass", self.line_pass)
        monkeypatch.setattr(page_mod, "reread", self.reread)
        monkeypatch.setattr(page_mod, "ask_crossed_out", self.ask_crossed_out)
        return self

    def page_pass(self, tiles):
        self.calls["page"] += 1
        out = []
        for t in tiles:
            r = self.page_override.get(t["path"], self.by_image.get(t["path"]))
            if r and not r.get("illegible"):
                out.append(dict(r))
        return out

    def line_pass(self, line):
        self.calls["line"] += 1
        return dict(self.by_image[line["crop_path"]])

    def reread(self, crop_path, a, b):
        self.calls["reread"] += 1
        self.reread_args.append((crop_path, a, b))
        if self.reread_choice == "neither":
            return {"choice": "neither", **self.reread_own}
        src = a if self.reread_choice == "A" else b
        return {"choice": self.reread_choice, **{k: src[k] for k in ("latex", "text", "kind", "illegible", "uncertain")}}

    def ask_crossed_out(self, crop_path):
        self.calls["crossed"] += 1
        return self.crossed_answer


def line_validator():
    from jsonschema import Draft202012Validator

    schema = json.loads(SCHEMA_PATH.read_text())
    line_schema = {**schema["properties"]["lines"]["items"], "$defs": schema["$defs"]}
    line_schema["required"] = [k for k in line_schema["required"] if k not in ("first_seen", "last_changed")]
    return Draft202012Validator(line_schema)
