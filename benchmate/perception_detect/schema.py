"""Schema validation helpers for the twin contract."""
from __future__ import annotations

import json
from functools import lru_cache

from jsonschema import Draft202012Validator

from .paths import TWIN_SCHEMA_PATH


@lru_cache(maxsize=1)
def twin_validator() -> Draft202012Validator:
    schema = json.loads(TWIN_SCHEMA_PATH.read_text())
    return Draft202012Validator(schema)


def validate_twin(twin: dict) -> list[str]:
    """Return a list of human-readable schema errors; empty list means valid."""
    errors = sorted(twin_validator().iter_errors(twin), key=lambda e: list(e.path))
    return [f"{'/'.join(str(p) for p in e.path) or '<root>'}: {e.message}" for e in errors]


def assert_valid_twin(twin: dict) -> None:
    errors = validate_twin(twin)
    if errors:
        raise ValueError("twin does not match contracts/twin.schema.json:\n" + "\n".join(errors))
