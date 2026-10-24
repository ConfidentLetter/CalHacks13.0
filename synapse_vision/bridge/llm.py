"""One thin Anthropic call for the tutor layer (judge + chat). Separate from T3's transcription client on purpose:
T3's cached few-shot prefix teaches *copying*; reusing it here would bias the judge.

Model from env SV_TUTOR_MODEL (optional override) → SV_MODEL → default. Key from ANTHROPIC_API_KEY only.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from jsonschema import Draft202012Validator

from bridge.compat import cfg, log

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_TIMEOUT_S = 40.0
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)
_client_lock = threading.Lock()
_client: dict[str, Any] = {}
_structured_ok = {"value": True}


class LLMError(RuntimeError):
    """The model call failed or never produced schema-valid JSON."""


def model_name() -> str:
    return os.environ.get("SV_TUTOR_MODEL") or os.environ.get("SV_MODEL") or DEFAULT_MODEL


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())


def _get_client(timeout_s: float):
    with _client_lock:
        key = f"{timeout_s}"
        if key not in _client:
            import anthropic

            _client[key] = anthropic.Anthropic(max_retries=int(cfg("bridge.sdk_max_retries", 1)), timeout=timeout_s)
        return _client[key]


def _strict(schema: Any) -> Any:
    """additionalProperties=false + all properties required (what output_config.format wants)."""
    if isinstance(schema, dict):
        out = {k: _strict(v) for k, v in schema.items() if k != "additionalProperties"}
        if out.get("type") == "object":
            out["additionalProperties"] = False
            out.setdefault("required", list(out.get("properties", {}).keys()))
        return out
    if isinstance(schema, list):
        return [_strict(v) for v in schema]
    return schema


def _text_of(response: Any) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()


def _create(client: Any, *, system: str, messages: list[dict], schema: dict | None, max_tokens: int) -> Any:
    import anthropic

    kwargs: dict[str, Any] = {"model": model_name(), "max_tokens": max_tokens, "system": system, "messages": messages,
                              "output_config": {"effort": cfg("bridge.effort", "medium")}}
    if schema is not None and _structured_ok["value"]:
        kwargs["output_config"] = {**kwargs["output_config"], "format": {"type": "json_schema", "schema": _strict(schema)}}
        try:
            return client.messages.create(**kwargs)
        except anthropic.BadRequestError as exc:  # platform/model without structured outputs or effort
            if "output_config" not in str(exc):
                raise
            _structured_ok["value"] = False
            kwargs.pop("output_config", None)
    try:
        return client.messages.create(**kwargs)
    except anthropic.BadRequestError as exc:
        if "output_config" not in str(exc) or "output_config" not in kwargs:
            raise
        kwargs.pop("output_config", None)
        return client.messages.create(**kwargs)


def ask_json(system: str, messages: list[dict], schema: dict, *, stage: str, max_tokens: int = 2048,
             timeout_s: float | None = None) -> dict:
    """Return schema-valid JSON from one call (one retry quoting the validation error). Raises LLMError."""
    if not available():
        raise LLMError("ANTHROPIC_API_KEY is not set on the backend")
    timeout = float(timeout_s or cfg("bridge.llm_timeout_s", DEFAULT_TIMEOUT_S))
    client = _get_client(timeout)
    validator = Draft202012Validator(schema)
    convo = list(messages)
    t0 = time.perf_counter()
    last_error = ""
    for attempt in range(2):
        try:
            response = _create(client, system=system, messages=convo, schema=schema, max_tokens=max_tokens)
        except Exception as exc:  # noqa: BLE001 - SDK errors become one honest LLMError
            log(stage, (time.perf_counter() - t0) * 1000.0, attempt=attempt, error=f"{type(exc).__name__}: {exc}")
            raise LLMError(f"model call failed: {type(exc).__name__}: {exc}") from exc
        usage = getattr(response, "usage", None)
        log(stage, (time.perf_counter() - t0) * 1000.0, attempt=attempt, model=model_name(),
            input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None))
        if response.stop_reason == "refusal":
            raise LLMError("model refused")
        text = _text_of(response)
        try:
            data = json.loads(_FENCE_RE.sub("", text))
            errors = [e.message for e in validator.iter_errors(data)]
        except (json.JSONDecodeError, ValueError) as exc:
            data, errors = None, [f"invalid JSON: {exc}"]
        if not errors and isinstance(data, dict):
            return data
        last_error = "; ".join(errors)[:600] or "not a JSON object"
        convo = convo + [{"role": "assistant", "content": text or "(empty)"},
                         {"role": "user", "content": "That was not valid for the required JSON shape: " + last_error
                          + ". Output the strict JSON object again, nothing else."}]
    raise LLMError(f"{stage}: no valid JSON after retry: {last_error}")
