"""Thin wrapper around the Anthropic Messages API (streaming). Model from BM_MODEL, key from the environment."""
from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Any

from reasoning.config import model_name

MAX_OUTPUT_TOKENS = 4096
REQUEST_TIMEOUT_S = float(os.environ.get("BM_MODEL_TIMEOUT_S", "45"))
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


class ModelError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelReply:
    text: str
    first_token_ms: float
    total_ms: float
    usage: dict[str, Any]
    model: str


def parse_json_object(text: str) -> dict[str, Any]:
    """Tolerate code fences or stray prose around the JSON object."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        obj = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ModelError("model output contained no JSON object")
        obj = json.loads(cleaned[start:end + 1])
    if not isinstance(obj, dict):
        raise ModelError("model output JSON is not an object")
    return obj


def _client():
    import anthropic
    return anthropic.Anthropic(timeout=REQUEST_TIMEOUT_S, max_retries=1)


def _request_kwargs(system: list[dict[str, Any]], messages: list[dict[str, Any]]) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"model": model_name(), "max_tokens": MAX_OUTPUT_TOKENS, "system": system, "messages": messages}
    effort = os.environ.get("BM_EFFORT", "low")
    if effort:
        kwargs["output_config"] = {"effort": effort}
    return kwargs


def complete(system: list[dict[str, Any]], messages: list[dict[str, Any]]) -> ModelReply:
    """Stream one completion; return the full text plus first-token and total latency."""
    import anthropic

    kwargs = _request_kwargs(system, messages)
    client = _client()
    for attempt in (0, 1):
        t0 = time.perf_counter()
        first: float | None = None
        try:
            with client.messages.stream(**kwargs) as stream:
                for event in stream:
                    if first is None and event.type == "content_block_delta" and getattr(event.delta, "type", "") == "text_delta":
                        first = (time.perf_counter() - t0) * 1000
                msg = stream.get_final_message()
            break
        except anthropic.BadRequestError as e:
            if attempt == 0 and "output_config" in kwargs and "output_config" in str(e):
                kwargs = {k: v for k, v in kwargs.items() if k != "output_config"}
                continue
            raise ModelError(f"bad request: {e.message}") from e
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            raise ModelError(f"api error: {e}") from e
    total = (time.perf_counter() - t0) * 1000
    if msg.stop_reason == "refusal":
        raise ModelError("model refused the request")
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    if msg.stop_reason == "max_tokens":
        raise ModelError("model output truncated at max_tokens")
    usage = {k: getattr(msg.usage, k, None) for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")}
    return ModelReply(text=text, first_token_ms=first if first is not None else total, total_ms=total, usage=usage, model=msg.model)
