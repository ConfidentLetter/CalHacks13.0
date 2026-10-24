"""One thin wrapper around the Anthropic SDK: strict-JSON calls on top of the cached few-shot prefix.

GreenMind "format reward" -> every response is schema-validated; invalid JSON is retried once with
the validation error quoted back; a second failure raises ModelResponseError (callers mark the line
illegible with confidence 0 — never guess).
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from typing import Any

from jsonschema import Draft202012Validator

from transcribe.compat import cfg, log
from transcribe.examples import prefix

DEFAULT_MODEL = "claude-sonnet-5-5"
DEFAULT_EFFORT = "medium"
DEFAULT_THINKING = "adaptive"
DEFAULT_CALL_TIMEOUT_S = 60.0  # measured tail under API throttling is ~27 s per call; keep well above it
_FENCE_RE = re.compile(r"^```(?:json)?\s*|\s*```$", re.S)
_structured_ok = {"value": True}
_client_lock = threading.Lock()
_client: dict[str, Any] = {}


class ModelResponseError(RuntimeError):
    """The model never produced schema-valid JSON (after one retry)."""


def model_name() -> str:
    env_var = cfg("transcribe.model_env", "SV_MODEL")
    return os.environ.get(env_var) or DEFAULT_MODEL


def get_client():
    """Lazily built, shared across threads. Key comes from ANTHROPIC_API_KEY (never hard-coded)."""
    with _client_lock:
        if "c" not in _client:
            import anthropic

            # A hung call must not stall the whole snapshot: the SDK raises APITimeoutError, the line degrades
            # honestly (single pass / no_reading) instead of blocking the budget.
            _client["c"] = anthropic.Anthropic(max_retries=int(cfg("transcribe.sdk_max_retries", 2)),
                                               timeout=float(cfg("transcribe.call_timeout_s", DEFAULT_CALL_TIMEOUT_S)))
        return _client["c"]


def _strict(schema: dict) -> dict:
    """Copy of a schema with additionalProperties=false everywhere (required by output_config.format)."""
    if isinstance(schema, dict):
        out = {k: _strict(v) for k, v in schema.items() if k != "additionalProperties"}
        if out.get("type") == "object":
            out["additionalProperties"] = False
            out.setdefault("required", list(out.get("properties", {}).keys()))
        return out
    if isinstance(schema, list):
        return [_strict(v) for v in schema]
    return schema


def _text_of(response) -> str:
    return "".join(b.text for b in response.content if getattr(b, "type", "") == "text").strip()


def _parse(text: str) -> Any:
    return json.loads(_FENCE_RE.sub("", text.strip()))


def _create(client, *, system, messages, schema, max_tokens):
    import anthropic

    kwargs: dict[str, Any] = {
        "model": model_name(), "max_tokens": max_tokens, "system": system, "messages": messages,
        "output_config": {"effort": cfg("transcribe.effort", DEFAULT_EFFORT)},
    }
    thinking = cfg("transcribe.thinking", DEFAULT_THINKING)  # "adaptive" | "between_tools" (= off on Sonnet 5.5)
    if thinking in ("adaptive", "between_tools"):
        kwargs["thinking"] = {"type": thinking}
    if _structured_ok["value"]:
        kwargs["output_config"] = {**kwargs["output_config"],
                                   "format": {"type": "json_schema", "schema": _strict(schema)}}
        try:
            return client.messages.create(**kwargs)
        except anthropic.BadRequestError as exc:  # platform/model without structured outputs
            if "output_config" not in str(exc):
                raise
            _structured_ok["value"] = False
            kwargs["output_config"] = {"effort": cfg("transcribe.effort", DEFAULT_EFFORT)}
    return client.messages.create(**kwargs)


def ask_json(content: list[dict], schema: dict, *, stage: str, max_tokens: int = 4096,
             use_prefix: bool = True) -> dict | list:
    """Send `content` (image/text blocks) after the cached prefix; return schema-valid parsed JSON.

    Raises ModelResponseError after one retry; raises the SDK's typed errors for transport failures.
    """
    client = get_client()
    system, messages = prefix() if use_prefix else ([], [])
    if not use_prefix:
        from transcribe.examples import system_blocks

        system = [dict(b) for b in system_blocks()]
    messages = messages + [{"role": "user", "content": content}]
    validator = Draft202012Validator(schema)
    last_error = ""
    t0 = time.perf_counter()
    for attempt in range(2):
        response = _create(client, system=system, messages=messages, schema=schema, max_tokens=max_tokens)
        if response.stop_reason == "max_tokens":
            max_tokens *= 2  # thinking tokens count against max_tokens; give the retry room
        usage = getattr(response, "usage", None)
        log(stage, (time.perf_counter() - t0) * 1000.0, attempt=attempt,
            cache_read=getattr(usage, "cache_read_input_tokens", None),
            cache_write=getattr(usage, "cache_creation_input_tokens", None),
            input_tokens=getattr(usage, "input_tokens", None), output_tokens=getattr(usage, "output_tokens", None))
        if response.stop_reason == "refusal":
            raise ModelResponseError(f"model refused ({stage})")
        text = _text_of(response)
        try:
            data = _parse(text)
            errors = [e.message for e in validator.iter_errors(data)]
        except (json.JSONDecodeError, ValueError) as exc:
            data, errors = None, [f"invalid JSON: {exc}"]
        if not errors:
            return data
        last_error = "; ".join(errors)[:800]
        if response.stop_reason == "max_tokens":
            last_error = f"response truncated at max_tokens; {last_error}"
        messages = messages + [
            {"role": "assistant", "content": [{"type": "text", "text": text or "(empty)"}]},
            {"role": "user", "content": [{"type": "text", "text":
                "That output was not valid for the required JSON shape: " + last_error
                + ". Output the strict JSON object again, same content, nothing else."}]},
        ]
    raise ModelResponseError(f"{stage}: no valid JSON after retry: {last_error}")
