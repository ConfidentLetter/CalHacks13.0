"""refine(): Phase 2 of answer(). Model-grounded, verified, and never worse than the rule diagnosis."""
from __future__ import annotations

import json
from typing import Any, Callable

from reasoning import model_client
from reasoning._telemetry import log as tlog, timed
from reasoning.citations import page_to_int
from reasoning.config import offline
from reasoning.profiles import load_profiles
from reasoning.prompt_builder import system_blocks, user_content
from reasoning.verify import verify

Completer = Callable[[list[dict[str, Any]], list[dict[str, Any]]], model_client.ModelReply]


def _offered_pages(hits: list[dict[str, Any]], rule_diagnosis: dict[str, Any]) -> set[tuple[str, int]]:
    pages = {(h["part_id"], p) for h in hits for p in [page_to_int(h.get("page"))] if p is not None}
    for f in rule_diagnosis.get("findings", []):
        for c in f.get("evidence", {}).get("datasheet", []):
            pages.add((c["part_id"], int(c["page"])))
    return pages


def refine(question: str, twin: dict, serial: list[str], frame_path: str, rule_diagnosis: dict,
           complete: Completer | None = None) -> dict:
    """Two model attempts at most (second one carries the validation error). Any failure -> rule_diagnosis."""
    if complete is None:
        if offline():
            tlog("refine_skipped", 0, reason="offline")
            return rule_diagnosis
        complete = model_client.complete
    lat: dict[str, float] = {}
    try:
        with timed("refine", lat, frame_id=rule_diagnosis.get("frame_id")):
            profiles = load_profiles()
            system = system_blocks(twin, profiles)
            with timed("search", lat):
                content, hits = user_content(question, twin, serial, frame_path, rule_diagnosis, profiles)
            offered = _offered_pages(hits, rule_diagnosis)
            messages: list[dict[str, Any]] = [{"role": "user", "content": content}]
            result = None
            for attempt in (1, 2):
                reply = complete(system, messages)
                lat[f"model_first_token_ms"] = round(reply.first_token_ms, 1)
                lat[f"model_total_ms"] = round(reply.total_ms, 1)
                tlog("model", reply.total_ms, attempt=attempt, first_token_ms=reply.first_token_ms, **reply.usage)
                try:
                    obj = model_client.parse_json_object(reply.text)
                    result, vlog = verify(obj, twin, profiles, rule_diagnosis, offered, question)
                except (model_client.ModelError, ValueError) as e:
                    result, vlog = None, [str(e)]
                for line in vlog:
                    tlog("verify", 0, note=line)
                if result is not None:
                    break
                messages = messages + [
                    {"role": "assistant", "content": reply.text or "{}"},
                    {"role": "user", "content": "That output was rejected: " + "; ".join(vlog)[:800] +
                     ". Return corrected JSON only, same shape, using only ids from the twin."},
                ]
        if result is None:
            return rule_diagnosis
        if not result["findings"] and rule_diagnosis.get("findings"):
            return rule_diagnosis
        result["latency_ms"] = {**rule_diagnosis.get("latency_ms", {}),
                                **{(k if k.endswith("_ms") else f"{k}_ms"): v for k, v in lat.items()}}
        return result
    except Exception as e:  # never let the model path remove the rule answer
        tlog("refine_failed", 0, error=repr(e)[:300])
        return rule_diagnosis
