"""The four kinds of model call T3 makes. Each returns None on failure (callers degrade honestly)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from transcribe.client import ModelResponseError, ask_json
from transcribe.compat import log
from transcribe.examples import image_block
from transcribe.ink import resolve, zoomed_copy
from transcribe.prompts import (CROSSED_OUT_PROMPT, LINE_PASS_PROMPT, LINE_PASS_PROMPT_NO_CONTEXT,
                                PAGE_PASS_PROMPT, REREAD_PROMPT)
from transcribe.schema import MODEL_LINE_SCHEMA

PAGE_SCHEMA = {"type": "object", "required": ["lines"],
               "properties": {"lines": {"type": "array", "items": MODEL_LINE_SCHEMA}}}
REREAD_SCHEMA = {"type": "object", "required": ["choice", "latex", "text", "kind", "illegible", "uncertain"],
                 "properties": {**MODEL_LINE_SCHEMA["properties"],
                                "choice": {"type": "string", "enum": ["A", "B", "neither"]}}}
# Thinking tokens count against max_tokens on adaptive-thinking models: leave room.
LINE_MAX_TOKENS = 2048
TINY_MAX_TOKENS = 512
PAGE_MAX_TOKENS = 12000
CROSSED_SCHEMA = {"type": "object", "required": ["crossed_out"], "properties": {"crossed_out": {"type": "boolean"}}}


def _safe(stage: str, fn, *args: Any) -> Any:
    try:
        return fn(*args)
    except ModelResponseError as exc:
        log(stage, 0.0, error=str(exc))
        return None
    except Exception as exc:  # noqa: BLE001 - SDK transport errors; the line degrades to low confidence
        log(stage, 0.0, error=f"{type(exc).__name__}: {exc}")
        return None


def get_tiles(dewarped_path: str) -> list[dict]:
    """T1's ink-balanced bands; whole page as one tile if T1's tile() is missing or raises."""
    try:
        from capture.page import tile

        tiles = tile(dewarped_path)
        if tiles:
            return tiles
    except Exception as exc:  # noqa: BLE001
        log("transcribe.tiles", 0.0, fallback="whole_page", error=f"{type(exc).__name__}: {exc}")
    return [{"path": dewarped_path, "bbox": None}]


def page_pass(tiles: list[dict]) -> list[dict] | None:
    def _call():
        blocks = [image_block(resolve(t["path"])) for t in tiles if Path(resolve(t["path"])).exists()]
        if not blocks:
            return None
        out = ask_json(blocks + [{"type": "text", "text": PAGE_PASS_PROMPT}], PAGE_SCHEMA,
                       stage="transcribe.page_pass", max_tokens=PAGE_MAX_TOKENS)
        return list(out["lines"])

    return _safe("transcribe.page_pass", _call)


def line_pass(line: dict) -> dict | None:
    def _call():
        ctx = line.get("context_crop_path")
        if ctx and Path(resolve(ctx)).exists():
            blocks = [image_block(resolve(ctx)), {"type": "text", "text": LINE_PASS_PROMPT}]
        else:
            blocks = [image_block(resolve(line["crop_path"])), {"type": "text", "text": LINE_PASS_PROMPT_NO_CONTEXT}]
        return ask_json(blocks, MODEL_LINE_SCHEMA, stage="transcribe.line_pass", max_tokens=LINE_MAX_TOKENS)

    return _safe("transcribe.line_pass", _call)


def reread(crop_path: str, a: dict, b: dict) -> dict | None:
    """3× zoom of the plain crop + both candidates: A, B, or neither (with its own reading)."""
    def _call():
        zoom = zoomed_copy(crop_path, 3.0)
        prompt = REREAD_PROMPT.format(a=_candidate(a), b=_candidate(b))
        return ask_json([image_block(zoom), {"type": "text", "text": prompt}], REREAD_SCHEMA,
                        stage="transcribe.reread", max_tokens=LINE_MAX_TOKENS)

    return _safe("transcribe.reread", _call)


def _candidate(r: dict) -> str:
    latex = r.get("latex") or ""
    return latex if latex else f'(text) {r.get("text") or ""}'


def ask_crossed_out(crop_path: str) -> bool | None:
    def _call():
        out = ask_json([image_block(resolve(crop_path)), {"type": "text", "text": CROSSED_OUT_PROMPT}],
                       CROSSED_SCHEMA, stage="transcribe.crossed_out", max_tokens=TINY_MAX_TOKENS)
        return bool(out["crossed_out"])

    return _safe("transcribe.crossed_out", _call)
