"""Schema loading and validation for the diagnosis contract."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
CONTRACTS = ROOT / "contracts"
DIAGNOSIS_SCHEMA_PATH = CONTRACTS / "diagnosis.schema.json"
TWIN_SCHEMA_PATH = CONTRACTS / "twin.schema.json"


@lru_cache(maxsize=None)
def load_schema(name: str) -> dict[str, Any]:
    """Load `contracts/<name>.schema.json`."""
    return json.loads((CONTRACTS / f"{name}.schema.json").read_text())


@lru_cache(maxsize=None)
def _validator(name: str) -> Draft202012Validator:
    return Draft202012Validator(load_schema(name))


def validation_errors(obj: dict[str, Any], name: str = "diagnosis") -> list[str]:
    """Human-readable list of schema violations (empty when valid)."""
    errs = sorted(_validator(name).iter_errors(obj), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errs]


def is_valid(obj: dict[str, Any], name: str = "diagnosis") -> bool:
    return not validation_errors(obj, name)


def assert_valid(obj: dict[str, Any], name: str = "diagnosis") -> dict[str, Any]:
    """Return `obj` if valid, else raise ValueError listing the violations."""
    errs = validation_errors(obj, name)
    if errs:
        raise ValueError(f"{name} schema violation: " + "; ".join(errs[:5]))
    return obj
