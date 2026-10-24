"""Schema loading and validation for the page twin and for model responses."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from transcribe.compat import REPO_ROOT

SCHEMA_PATH = REPO_ROOT / "contracts" / "page_twin.schema.json"
MOCK_TWIN_PATH = REPO_ROOT / "mocks" / "page_twin_product_rule.json"

LINE_KINDS = ("math", "text", "mixed", "diagram_label")

# What every model call must return (Step 2 prompt contract). Strictly validated; see client.py.
MODEL_LINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["latex", "text", "kind", "illegible", "uncertain"],
    "properties": {
        "latex": {"type": "string"},
        "text": {"type": "string"},
        "kind": {"type": "string", "enum": list(LINE_KINDS)},
        "illegible": {"type": "boolean"},
        "uncertain": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["span", "alternatives"],
                "properties": {
                    "span": {"type": "string"},
                    "alternatives": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    },
    "additionalProperties": True,
}

MODEL_PAGE_SCHEMA: dict[str, Any] = {"type": "array", "items": MODEL_LINE_SCHEMA}


@lru_cache(maxsize=1)
def load_twin_schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _twin_validator() -> Draft202012Validator:
    return Draft202012Validator(load_twin_schema())


def twin_errors(twin: dict) -> list[str]:
    """All schema violations as readable strings (empty list = valid)."""
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '<root>'}: {e.message}"
            for e in _twin_validator().iter_errors(twin)]


def validate_twin(twin: dict) -> dict:
    """Raise ValueError listing every violation; return the twin unchanged when valid."""
    errors = twin_errors(twin)
    if errors:
        raise ValueError("page twin fails schema:\n  " + "\n  ".join(errors))
    return twin


def load_mock_twin() -> dict:
    return json.loads(MOCK_TWIN_PATH.read_text(encoding="utf-8"))


def validate_model_line(obj: Any) -> list[str]:
    return [e.message for e in Draft202012Validator(MODEL_LINE_SCHEMA).iter_errors(obj)]


def validate_model_page(obj: Any) -> list[str]:
    return [e.message for e in Draft202012Validator(MODEL_PAGE_SCHEMA).iter_errors(obj)]
